#!/usr/bin/env python3
"""Re-file pred_recent_games under each game's Eastern date.

Until #173, ``update_recent_games`` stored every API-Sports box score under the
UTC date it queried, so each evening tip-off (7 pm ET = 00:00 UTC) sat a day
late. New rows are right; old rows are not, and a stored row cannot tell us
whether its game was an afternoon or an evening one. So the repair replaces a
season's rows wholesale: back them up, delete them, and re-pull every game day
with the fixed ingest.

Dry run by default (database reads only, no API calls):

  cd backend
  PYTHONPATH=. .venv/bin/python scripts/nba_recent_games_date_repair.py --seasons 2026
  PYTHONPATH=. .venv/bin/python scripts/nba_recent_games_date_repair.py --seasons 2026 --apply

--seasons takes league start years (2026 = 2026-27). Each season's window runs
from opening night to June 30 of the next year, clipped to today. Cost is about
one API-Sports call per game day plus one per game (~1,500 per full season).
After --apply, retrain the NBA prop models and let the nightly pipeline rebuild
derived tables.

Before deleting, rows are copied to pred_recent_games_bak_<season> (the script
refuses to run if that table already exists). To restore a season:

  delete from pred_recent_games where game_date between '<start>' and '<end>';
  insert into pred_recent_games select * from pred_recent_games_bak_<season>;

Needs DATABASE_URL; --apply also needs NBA_API_KEY.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba._season import regular_season_start

# Rows are only expected up to this fraction below the pre-repair count before
# the script calls the re-ingest suspect (re-pulls drop non-NBA/offseason lines).
MIN_RESTORED_FRACTION = 0.9


def season_window(start_year: int, today: date) -> tuple[date, date]:
    """Rows to replace: opening night through June 30 (clipped to today)."""
    start = regular_season_start(start_year)
    end = min(date(start_year + 1, 6, 30), today)
    return start, end


def utc_days_to_refetch(start: date, end: date, today: date) -> list[date]:
    """UTC days whose games land in [start, end] in Eastern time.

    An evening game on ET day ``end`` belongs to UTC day ``end + 1``, so the
    window reaches one day further, never past today.
    """
    last = min(end + timedelta(days=1), today)
    days = []
    day = start
    while day <= last:
        days.append(day)
        day += timedelta(days=1)
    return days


def backup_table(start_year: int) -> str:
    return f"pred_recent_games_bak_{int(start_year)}"


def _count(db, start: date, end: date) -> int:
    return db.execute(
        text(
            "select count(*) from pred_recent_games "
            "where game_date between :s and :e"
        ),
        {"s": start, "e": end},
    ).scalar_one()


def _by_date(db, start: date, end: date):
    return db.execute(
        text(
            "select game_date, count(*), count(distinct opponent_team_id) "
            "from pred_recent_games where game_date between :s and :e "
            "group by 1 order by 1"
        ),
        {"s": start, "e": end},
    ).all()


def repair_season(start_year: int, apply: bool, today: date) -> bool:
    start, end = season_window(start_year, today)
    db_end = min(end + timedelta(days=1), today)  # rows the old ingest put here
    days = utc_days_to_refetch(start, end, today)
    db = SessionLocal()
    try:
        before = _count(db, start, db_end)
        print(f"\n== season {start_year}-{str(start_year + 1)[-2:]}: {start} .. {end}")
        print(f"   rows to replace: {before} (dated {start} .. {db_end})")
        print(f"   game days to re-pull: {len(days)}")
        if not apply:
            for game_date, lines, teams in _by_date(db, start, db_end)[-10:]:
                print(f"   {game_date}  lines={lines:<4} teams={teams}")
            print("   dry run: nothing changed (pass --apply)")
            return True

        from app.services.etl.nba.update_recent_games import _process_day

        bak = backup_table(start_year)
        exists = db.execute(
            text("select to_regclass(:t)"), {"t": bak}
        ).scalar_one_or_none()
        if exists:
            print(f"   refusing: backup table {bak} already exists", file=sys.stderr)
            return False
        db.execute(
            text(
                f"create table {bak} as select * from pred_recent_games "
                "where game_date between :s and :e"
            ),
            {"s": start, "e": db_end},
        )
        db.execute(
            text("delete from pred_recent_games where game_date between :s and :e"),
            {"s": start, "e": db_end},
        )
        db.commit()
        print(f"   backed up {before} rows to {bak}, then deleted them")
    finally:
        db.close()

    added = updated = 0
    try:
        for day in days:
            a, u = _process_day(day)
            added += a
            updated += u
            print(f"   {day}: +{a}")
    except Exception as exc:
        print(f"   re-pull failed on the way: {exc!r}", file=sys.stderr)
        print(f"   restore from {bak} (see the script docstring)", file=sys.stderr)
        return False

    db = SessionLocal()
    try:
        after = _count(db, start, db_end)
    finally:
        db.close()
    print(f"   re-pulled {added + updated} lines; table now has {after} rows")
    if before and after < before * MIN_RESTORED_FRACTION:
        print(
            f"   WARNING: only {after}/{before} rows came back; "
            f"check the log for empty box scores before relying on it "
            f"(backup: {bak})",
            file=sys.stderr,
        )
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--seasons",
        default=str(
            now_eastern().year if now_eastern().month >= 10 else now_eastern().year - 1
        ),
        help="comma-separated league start years (default: current season)",
    )
    parser.add_argument("--apply", action="store_true", help="write changes")
    args = parser.parse_args()
    today = now_eastern().date()
    ok = True
    for year in sorted(int(y) for y in args.seasons.split(",") if y.strip()):
        ok = repair_season(year, args.apply, today) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
