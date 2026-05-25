#!/usr/bin/env python3
"""Validate NFL prediction tables have recent rows (requires DATABASE_URL)."""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, text

from app.services.etl.nfl import nfl_common

NFL_IN_SEASON_MONTHS = {9, 10, 11, 12, 1, 2}


def validate_week_rollover_offline() -> bool:
    """Labor-day week math without DB (Phase 4.1 acceptance)."""
    season = 2025
    with patch("app.services.etl.nfl.nfl_common.get_nfl_season", return_value=season):
        w_before = nfl_common.get_current_nfl_week(today=date(2025, 9, 3))
        w_week1 = nfl_common.get_current_nfl_week(today=date(2025, 9, 5))
        w_week2 = nfl_common.get_current_nfl_week(today=date(2025, 9, 12))
    if w_before != 1 or w_week1 != 1 or w_week2 != 2:
        print(
            f"  [fail] week rollover: before={w_before} week1={w_week1} week2={w_week2}"
        )
        return False
    print("  [ok] nfl_common week rollover (offline)")
    return True


def main() -> int:
    if not validate_week_rollover_offline():
        return 1

    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set — skip DB validation")
        return 0

    in_season = date.today().month in NFL_IN_SEASON_MONTHS
    if not in_season:
        print(
            "NFL off-season — skipping prediction row requirements (orchestrator-only check)"
        )

    engine = create_engine(url)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    checks = [
        ("pred_qb_predictions", "game_date", today),
        ("pred_kicker_predictions", "game_date", today),
        ("pred_kickers", None, None),
        ("pred_qb_actuals", "game_date", week_start),
        ("pred_kicker_actuals", "game_date", week_start),
    ]

    ok = True
    with engine.connect() as conn:
        for table, date_col, d in checks:
            if date_col and d:
                q = text(  # nosec B608 — table/column from internal allowlist
                    f"SELECT COUNT(*) FROM {table} WHERE {date_col} >= :d"
                )
                n = conn.execute(q, {"d": d}).scalar() or 0
                label = f"{table} ({date_col}>={d})"
            else:
                n = (
                    conn.execute(
                        text(f"SELECT COUNT(*) FROM {table}")  # nosec B608
                    ).scalar()
                    or 0
                )
                label = table
            status = "ok" if n > 0 else "empty"
            if n == 0 and table.endswith("_predictions") and in_season:
                ok = False
            print(f"  [{status}] {label}: {n} rows")

    if not in_season:
        print(
            "PASS (off-season): run run_nfl_update_pipeline in-season for full table check."
        )
        return 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
