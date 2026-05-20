#!/usr/bin/env python3
"""Validate NFL prediction tables have recent rows (requires DATABASE_URL)."""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from sqlalchemy import create_engine, text


NFL_IN_SEASON_MONTHS = {9, 10, 11, 12, 1, 2}


def main() -> int:
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
