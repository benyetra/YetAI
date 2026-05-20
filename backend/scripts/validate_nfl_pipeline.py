#!/usr/bin/env python3
"""Validate NFL prediction tables have recent rows (requires DATABASE_URL)."""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from sqlalchemy import create_engine, text


def main() -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set — skip DB validation")
        return 0

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
                q = text(
                    f"SELECT COUNT(*) FROM {table} WHERE {date_col} >= :d"  # noqa: S608
                )
                n = conn.execute(q, {"d": d}).scalar() or 0
                label = f"{table} ({date_col}>={d})"
            else:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
                label = table
            status = "ok" if n > 0 else "empty"
            if n == 0 and table.endswith("_predictions"):
                ok = False
            print(f"  [{status}] {label}: {n} rows")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
