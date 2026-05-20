#!/usr/bin/env python3
"""Validate NHL prediction tables have recent rows (requires DATABASE_URL)."""

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
    yesterday = today - timedelta(days=1)

    checks = [
        ("pred_nhl_goalie_predictions", "game_date", today),
        ("pred_nhl_player_shots_predictions", "game_date", today),
        ("pred_nhl_team_totals_predictions", "game_date", today),
        ("pred_nhl_goalie_actuals", "game_date", yesterday),
        ("pred_nhl_goalies", None, None),
        ("pred_nhl_teams", None, None),
    ]

    ok = True
    with engine.connect() as conn:
        for table, date_col, d in checks:
            if date_col and d:
                q = text(  # nosec B608 — table/column from internal allowlist
                    f"SELECT COUNT(*) FROM {table} WHERE {date_col} = :d"
                )
                n = conn.execute(q, {"d": d}).scalar() or 0
                label = f"{table} ({date_col}={d})"
            else:
                n = (
                    conn.execute(
                        text(f"SELECT COUNT(*) FROM {table}")  # nosec B608
                    ).scalar()
                    or 0
                )
                label = table
            status = "ok" if n > 0 else "empty"
            if n == 0:
                ok = False
            print(f"  [{status}] {label}: {n} rows")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
