"""Backfill pred_nba_spread_actuals from ESPN final scores.

The daily store_spread_actuals task fetched a hardcoded 2024-25 season, so the
table stayed empty: spread Elo sat at its initial value for every team and the
spread model had nothing to train on. This fills past seasons from ESPN's
scoreboard (regular season, play-in and playoffs; preseason skipped).

Dry run by default; --apply upserts on (game_date, home, away), so re-running
is safe and rows the daily task already wrote are only refreshed.

    PYTHONPATH=. python3 scripts/nba_backfill_spread_actuals.py \
        --from 2024-10-22 --to 2026-06-30 [--apply]
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Callable

from app.services.etl.nba._espn import fetch_final_scores
from app.services.etl.nba._season import is_offseason_date

# A full NBA season is 1,230 regular-season games plus ~80 play-in/playoff.
MIN_GAMES_PER_SEASON = 1200


def actual_rows(game_date: date, finals: list[dict]) -> list[dict]:
    rows = []
    for g in finals:
        margin = g["home_score"] - g["away_score"]
        rows.append(
            {
                "game_date": game_date,
                "home_team_name": g["home_team_name"],
                "away_team_name": g["away_team_name"],
                "home_score": g["home_score"],
                "away_score": g["away_score"],
                "actual_margin": margin,
                "home_won": margin > 0,
                "created_at": datetime.utcnow(),
            }
        )
    return rows


def collect(
    start: date,
    end: date,
    fetch: Callable[[date], list[dict]] = fetch_final_scores,
    pause: float = 0.2,
) -> tuple[list[dict], list[date]]:
    """Rows for every in-season date in [start, end]; returns (rows, failed_dates)."""
    rows: list[dict] = []
    failed: list[date] = []
    d = start
    while d <= end:
        if not is_offseason_date(d):
            try:
                rows.extend(actual_rows(d, fetch(d)))
            except Exception as exc:  # noqa: BLE001 - retry once, then report
                time.sleep(2)
                try:
                    rows.extend(actual_rows(d, fetch(d)))
                except Exception:
                    print(f"WARNING: {d} fetch failed: {exc}", file=sys.stderr)
                    failed.append(d)
            if pause:
                time.sleep(pause)
        d += timedelta(days=1)
    return rows, failed


def season_counts(rows: list[dict]) -> Counter:
    """Games per season, keyed by the season's start year."""
    return Counter(
        r["game_date"].year if r["game_date"].month >= 7 else r["game_date"].year - 1
        for r in rows
    )


def write(rows: list[dict]) -> int:
    from app.core.database import SessionLocal
    from app.models.predictions_models import NBASpreadActuals
    from app.services.etl.wnba._db_upsert import upsert_many

    db = SessionLocal()
    try:
        written = 0
        for i in range(0, len(rows), 500):
            written += upsert_many(
                db,
                NBASpreadActuals,
                rows[i : i + 500],
                conflict_keys=["game_date", "home_team_name", "away_team_name"],
            )
        db.commit()
        return written
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    p.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    p.add_argument("--apply", action="store_true", help="write to the database")
    args = p.parse_args(argv)

    rows, failed = collect(args.start, args.end)
    counts = season_counts(rows)
    teams = {r["home_team_name"] for r in rows} | {r["away_team_name"] for r in rows}
    print(f"fetched {len(rows)} games across {len(teams)} teams")
    for year in sorted(counts):
        flag = "" if counts[year] >= MIN_GAMES_PER_SEASON else "  (partial window)"
        print(f"  {year}-{(year + 1) % 100:02d}: {counts[year]} games{flag}")
    if failed:
        print(f"ERROR: {len(failed)} dates failed: {', '.join(map(str, failed))}")
        print("Nothing written; re-run to retry.")
        return 1
    if not args.apply:
        print("Dry run — pass --apply to write.")
        return 0
    print(f"upserted {write(rows)} rows into pred_nba_spread_actuals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
