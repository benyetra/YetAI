"""Refresh pred_wnba_game_lines from The Odds API.

Stores ONE consensus row per game (simple average across all books that offer
the market). This differs from the NBA equivalent which stores per-book rows.
Spec: docs/superpowers/specs/2026-05-21-wnba-support-design.md (Section 4c).
"""

from __future__ import annotations

import logging
import os

from app.core.database import SessionLocal
from app.models.predictions_models import WNBAGameLines
from app.services.etl._game_start import not_started
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._game_lines_odds import game_line_rows_from_events

logger = logging.getLogger(__name__)

ODDS_API_KEY_ENV = "ODDS_API_KEY"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4/sports"
SPORT = "basketball_wnba"


def _odds_get(path: str, params: dict) -> list | dict | None:
    from app.services.etl.wnba.historical_game_lines import resolve_odds_api_key

    api_key = resolve_odds_api_key()
    if not api_key:
        raise RuntimeError(f"{ODDS_API_KEY_ENV} env var is required")
    from app.services.odds_api_sync import sync_odds_get

    resp = sync_odds_get(
        f"{ODDS_BASE_URL}/{path}",
        params={"apiKey": api_key, **params},
        caller=f"etl.wnba.update_game_lines.{path}",
        timeout=20,
        raise_for_status=False,
    )
    if resp is None:
        return None
    if resp.status_code != 200:
        logger.warning("odds-api %s -> %s: %s", path, resp.status_code, resp.text[:200])
        return None
    return resp.json()


def _keep_stored_lines(db, rows: list[dict]) -> None:
    """A book that lists no market right now must not blank a stored line."""
    stored = {
        (g.game_date, g.home_team_name, g.away_team_name): g
        for g in db.query(WNBAGameLines)
        .filter(WNBAGameLines.game_date.in_({r["game_date"] for r in rows}))
        .all()
    }
    for row in rows:
        old = stored.get((row["game_date"], row["home_team_name"], row["away_team_name"]))
        for key, value in row.items():
            if value is None and old is not None:
                row[key] = getattr(old, key, None)


def run(now=None) -> dict:
    payload = _odds_get(
        f"{SPORT}/odds",
        params={
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
        },
    )
    if not isinstance(payload, list):
        return {"status": "no_data", "games": 0}

    # Started games (live in the feed) are frozen as users last saw them.
    upsert_rows_list = not_started(
        game_line_rows_from_events(payload),
        lambda r: (r["game_time"], r["game_date"]),
        now=now,
    )
    if not upsert_rows_list:
        return {"status": "no_data", "games": 0}

    db = SessionLocal()
    try:
        _keep_stored_lines(db, upsert_rows_list)
        upsert_many(
            db,
            WNBAGameLines,
            upsert_rows_list,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
        db.commit()
        return {"status": "ok", "games": len(upsert_rows_list)}
    finally:
        db.close()


if __name__ == "__main__":
    from pathlib import Path

    try:
        from dotenv import load_dotenv

        backend_root = Path(__file__).resolve().parents[4]
        for name in (".env.production", ".env"):
            env_path = backend_root / name
            if env_path.is_file():
                load_dotenv(env_path)
        public = os.environ.get("DATABASE_PUBLIC_URL", "").strip()
        db_url = os.environ.get("DATABASE_URL", "").strip()
        if public and (
            not db_url
            or "railway.internal" in db_url
            or ":port" in db_url
            or "@host:" in db_url
        ):
            os.environ["DATABASE_URL"] = public
    except ImportError:
        pass
    print(run())
