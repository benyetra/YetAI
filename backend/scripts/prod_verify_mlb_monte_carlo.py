#!/usr/bin/env python3
"""Verify MLB Monte Carlo: DB column, game rows, and predictions API.

DB: uses app session (``.env`` / ``.env.production`` via ``init_session``), not raw
``DATABASE_URL`` (often unset in the shell).

API: hits production (or ``--api``) — ``404`` on ``/mlb/p-over-total`` means the
new route is not deployed yet (expected until Railway deploy).

Usage:
  cd backend
  PYTHONPATH=. python3 scripts/prod_verify_mlb_monte_carlo.py
  PYTHONPATH=. python3 scripts/prod_verify_mlb_monte_carlo.py --api http://127.0.0.1:8000
  PYTHONPATH=. python3 scripts/prod_verify_mlb_monte_carlo.py --db-only
  PYTHONPATH=. python3 scripts/prod_verify_mlb_monte_carlo.py --run-pipeline
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date

DEFAULT_API = os.getenv("YETAI_API", "https://api.yetai.app")


def _login(api: str) -> str:
    token = (os.getenv("YETAI_ADMIN_JWT") or os.getenv("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    email = os.getenv("YETAI_ADMIN_EMAIL")
    password = os.getenv("YETAI_ADMIN_PASSWORD")
    if not email or not password:
        raise SystemExit(
            "Set YETAI_ADMIN_JWT or YETAI_ADMIN_EMAIL + YETAI_ADMIN_PASSWORD for API checks"
        )
    payload = json.dumps({"email_or_username": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise SystemExit(
            f"Cannot reach {api} ({e}). "
            "Start local API: cd backend && PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload "
            "Or omit --api to use https://api.yetai.app (after deploy)."
        ) from e
    token = data.get("access_token") or data.get("token")
    if not token:
        raise SystemExit("login missing access_token")
    return token


def _get(api: str, path: str, token: str) -> tuple[dict | None, str | None]:
    """Returns (json_body, error_message)."""
    req = urllib.request.Request(
        f"{api.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:400]
        return None, f"HTTP {e.code} {path}: {body}"


def _check_db_via_app() -> dict:
    """Same DB path as Celery / game projection pipeline."""
    from sqlalchemy import inspect, text

    from app.services.etl.mlb._db import close_session, db_session, init_session

    session = init_session()
    try:
        insp = inspect(session.get_bind())
        out: dict = {"skipped": False, "source": "app_session"}
        if not insp.has_table("pred_game_projections"):
            out["error"] = "pred_game_projections missing"
            return out

        cols = {c["name"] for c in insp.get_columns("pred_game_projections")}
        out["has_sim_distribution_column"] = "sim_distribution" in cols

        today = date.today()
        row = (
            session.execute(
                text(
                    """
                    SELECT COUNT(*) AS n,
                           COUNT(sim_distribution) AS with_sim,
                           COUNT(*) FILTER (WHERE model_version LIKE '%mc%') AS with_mc_tag
                    FROM pred_game_projections
                    WHERE date = :d
                    """
                ),
                {"d": today},
            )
            .mappings()
            .first()
        )
        out["today"] = today.isoformat()
        out.update(dict(row))
        sample = (
            db_session.execute(
                text(
                    """
                    SELECT game_id, model_version,
                           sim_distribution->>'n_sims' AS n_sims
                    FROM pred_game_projections
                    WHERE date = :d AND sim_distribution IS NOT NULL
                    LIMIT 1
                    """
                ),
                {"d": today},
            )
            .mappings()
            .first()
        )
        if sample:
            out["sample"] = dict(sample)
        return out
    finally:
        close_session()


def _check_api(api: str, token: str) -> dict:
    today = date.today().isoformat()
    out: dict = {"api": api, "date": today, "errors": []}

    slate, err = _get(api, f"/api/v1/predictions/mlb?date={today}&limit=20", token)
    if err:
        out["errors"].append(err)
        return out

    games = slate.get("game_projections") or []
    out["game_count"] = len(games)
    sample = games[0] if games else {}
    out["sample_game_id"] = sample.get("game_id")
    out["sample_model_version"] = sample.get("model_version")
    out["sample_has_sim_distribution"] = sample.get("sim_distribution") is not None
    out["sample_sim_n_sims"] = (sample.get("sim_distribution") or {}).get("n_sims")

    with_line, err = _get(
        api,
        f"/api/v1/predictions/mlb?date={today}&limit=5&total_line=8.5",
        token,
    )
    if err:
        out["errors"].append(err)
        out["total_line_param_deployed"] = False
    else:
        line_games = with_line.get("game_projections") or []
        out["total_line_param_deployed"] = True
        out["line_param_ok"] = (
            all("p_over_total" in g and "p_under_total" in g for g in line_games[:3])
            if line_games
            else None
        )
        out["line_sample_p_over"] = (line_games[0] if line_games else {}).get(
            "p_over_total"
        )

    gid = sample.get("game_id") or 825005
    p_over, err = _get(
        api,
        f"/api/v1/predictions/mlb/p-over-total?game_id={gid}&line=8.5&date={today}",
        token,
    )
    if err:
        out["errors"].append(err)
        out["p_over_endpoint_deployed"] = "404" not in err
        if "404" in err:
            out["p_over_endpoint_hint"] = (
                "Route not on this API host — deploy backend with monte_carlo + "
                "predictions changes, or use --api http://127.0.0.1:8000 for local."
            )
    else:
        out["p_over_endpoint_deployed"] = True
        out["p_over_endpoint"] = p_over.get("p_over_total")

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify MLB Monte Carlo")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument(
        "--db-only",
        action="store_true",
        help="Only check database via app session",
    )
    parser.add_argument(
        "--run-pipeline",
        action="store_true",
        help="Enqueue MLB game projection pipeline via admin API",
    )
    args = parser.parse_args()

    ok = True

    print("=== DB (app session) ===")
    try:
        db = _check_db_via_app()
        print(json.dumps(db, indent=2, default=str))
        if not db.get("has_sim_distribution_column"):
            print("FAIL: sim_distribution column missing — alembic upgrade head")
            ok = False
        elif db.get("n", 0) == 0:
            print("WARN: no game projections for today")
        elif db.get("with_sim", 0) == 0:
            print("WARN: no sim_distribution rows today — run game pipeline")
            ok = False
        else:
            print(
                f"OK: {db.get('with_sim')}/{db.get('n')} games with MC "
                f"({db.get('with_mc_tag')} mc-tagged versions)"
            )
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        print("FAIL: could not query DB via app session")
        ok = False

    if args.run_pipeline:
        token = _login(args.api)
        body = json.dumps({"task_name": "mlb.run_game_projections"}).encode()
        req = urllib.request.Request(
            f"{args.api.rstrip('/')}/api/admin/celery/enqueue",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            print("enqueued", json.loads(resp.read().decode()))

    if args.db_only:
        print("\n" + ("OK" if ok else "NEEDS ATTENTION"))
        return 0 if ok else 1

    print("\n=== API ===")
    try:
        token = _login(args.api)
        api_out = _check_api(args.api, token)
        print(json.dumps(api_out, indent=2, default=str))

        if api_out.get("errors"):
            for err in api_out["errors"]:
                print(err)
            if api_out.get("p_over_endpoint_deployed") is False:
                print(
                    "\nNote: 404 on p-over-total is expected on production until you "
                    "deploy the branch with the new endpoint. DB/MC pipeline can still be OK."
                )
                # Do not fail overall check solely for undeployed route on prod
                if "127.0.0.1" in args.api or "localhost" in args.api:
                    ok = False
            else:
                ok = False

        if api_out.get("game_count", 0) == 0:
            print("WARN: API returned no games for today")
        if api_out.get("sample_has_sim_distribution") is False and api_out.get(
            "game_count", 0
        ):
            print(
                "WARN: API game row missing sim_distribution (old deploy or no MC run)"
            )
        if api_out.get("line_param_ok") is False:
            print("FAIL: total_line=8.5 did not add p_over_total")
            ok = False
        if api_out.get("total_line_param_deployed") is False:
            print("WARN: total_line query param not on deployed API yet")

        mv = api_out.get("sample_model_version") or ""
        if api_out.get("game_count", 0) and "mc" not in mv:
            print(f"WARN: model_version lacks mc tag (got {mv!r})")
    except SystemExit as e:
        print(f"API check skipped: {e}")
        if "127.0.0.1" in args.api or "localhost" in args.api:
            print("(DB can still be OK — start uvicorn on :8000 to test API locally)")

    print("\n" + ("OK" if ok else "NEEDS ATTENTION"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
