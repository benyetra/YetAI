#!/usr/bin/env python3
"""Diagnose auto-pick runs (prod via admin API or local DATABASE_URL).

Examples:
  export YETAI_ADMIN_JWT='...'
  PYTHONPATH=. python3 scripts/diagnose_auto_pick.py --run-id 1

  DATABASE_URL='postgresql://...' PYTHONPATH=. python3 scripts/diagnose_auto_pick.py --run-id 1 --local
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_API = "https://api.yetai.app"


def _get_token(api: str) -> str:
    token = os.getenv("YETAI_ADMIN_JWT") or os.getenv("ADMIN_TOKEN")
    if token:
        return token
    email = os.getenv("YETAI_ADMIN_EMAIL")
    password = os.getenv("YETAI_ADMIN_PASSWORD")
    if email and password:
        payload = json.dumps(
            {"email_or_username": email, "password": password}
        ).encode()
        req = urllib.request.Request(
            f"{api}/api/auth/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        token = data.get("access_token") or data.get("token")
        if token:
            return token
    raise SystemExit("Set YETAI_ADMIN_JWT or YETAI_ADMIN_EMAIL + YETAI_ADMIN_PASSWORD")


def _fetch_api(api: str, path: str) -> dict:
    token = _get_token(api)
    req = urllib.request.Request(
        f"{api.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode()[:800]}") from e


def _fetch_local(run_id: int | None) -> dict:
    from app.core.database import SessionLocal
    from app.services.auto_pick.diagnostics import get_run_diagnostics

    db = SessionLocal()
    try:
        if run_id is None:
            from app.models.database_models import AutoPickRun

            run = db.query(AutoPickRun).order_by(AutoPickRun.id.desc()).first()
            if not run:
                raise SystemExit("No auto_pick_runs rows")
            run_id = run.id
        return get_run_diagnostics(db, run_id)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-pick run diagnostics")
    parser.add_argument("--api", default=os.getenv("YETAI_API", DEFAULT_API))
    parser.add_argument("--run-id", type=int, default=None)
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use DATABASE_URL from env instead of admin API",
    )
    args = parser.parse_args()

    if args.local:
        data = _fetch_local(args.run_id)
    else:
        path = (
            f"/api/admin/yetai-picks/runs/{args.run_id}/diagnostics"
            if args.run_id
            else "/api/admin/yetai-picks/runs/latest"
        )
        data = _fetch_api(args.api, path)

    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
