#!/usr/bin/env python3
"""
League Vault pilot sync — ingest Sleeper and/or ESPN leagues into lv_* tables.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services.league_vault.ingest.espn_history import (
    ingest_espn_league,
)  # noqa: E402
from app.services.league_vault.ingest.sleeper_history import (
    ingest_sleeper_league,
)  # noqa: E402


def _load_env() -> None:
    env_path = BACKEND / ".env.leaguevault.local"
    if env_path.exists():
        load_dotenv(env_path)
    load_dotenv(BACKEND / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="League Vault pilot sync")
    parser.add_argument("--sleeper-only", action="store_true")
    parser.add_argument("--espn-only", action="store_true")
    args = parser.parse_args()

    _load_env()

    if SessionLocal is None:
        print("DATABASE_URL required")
        return 1

    run_sleeper = not args.espn_only
    run_espn = not args.sleeper_only

    db = SessionLocal()
    try:
        if run_sleeper:
            league_id = os.environ.get("SLEEPER_LEAGUE_ID", "")
            if not league_id:
                print("SLEEPER_LEAGUE_ID not set — skipping Sleeper")
            else:
                stats = ingest_sleeper_league(
                    db,
                    league_id=league_id,
                    slug=os.environ.get("SLEEPER_SITE_SLUG", "mikes-hard-league"),
                    display_name=os.environ.get(
                        "SLEEPER_SITE_NAME", "Mike's Hard League"
                    ),
                )
                print("Sleeper ingest:", stats)

        if run_espn:
            league_id = os.environ.get("ESPN_LEAGUE_ID", "838295")
            start = int(os.environ.get("ESPN_START_SEASON", "2010"))
            end = int(os.environ.get("ESPN_END_SEASON", "2025"))
            stats = ingest_espn_league(
                db,
                league_id=league_id,
                slug=os.environ.get("ESPN_SITE_SLUG", "espn-838295"),
                display_name=os.environ.get("ESPN_SITE_NAME", "ESPN League 838295"),
                start_season=start,
                end_season=end,
            )
            print("ESPN ingest:", stats)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
