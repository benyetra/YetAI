"""Backfill derived eFG% and TS% on pred_wnba_recent_games from traditional box scores."""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import SessionLocal

EFG_SQL = """
UPDATE pred_wnba_recent_games
SET effective_field_goal_percentage =
    (field_goals_made + 0.5 * COALESCE(three_pt_made, 0)) / NULLIF(fg_attempts, 0)
WHERE effective_field_goal_percentage IS NULL
  AND field_goals_made IS NOT NULL
  AND fg_attempts IS NOT NULL
  AND fg_attempts > 0
"""

TS_SQL = """
UPDATE pred_wnba_recent_games
SET true_shooting_percentage =
    points / NULLIF(2.0 * (fg_attempts + 0.44 * COALESCE(ft_attempts, 0)), 0)
WHERE true_shooting_percentage IS NULL
  AND points IS NOT NULL
  AND fg_attempts IS NOT NULL
  AND (fg_attempts + COALESCE(ft_attempts, 0)) > 0
"""


def run(*, dry_run: bool = False) -> dict:
    db = SessionLocal()
    try:
        efg_pending = db.execute(
            text(
                """
                SELECT COUNT(*) FROM pred_wnba_recent_games
                WHERE effective_field_goal_percentage IS NULL
                  AND field_goals_made IS NOT NULL
                  AND fg_attempts IS NOT NULL AND fg_attempts > 0
                """
            )
        ).scalar()
        ts_pending = db.execute(
            text(
                """
                SELECT COUNT(*) FROM pred_wnba_recent_games
                WHERE true_shooting_percentage IS NULL
                  AND points IS NOT NULL AND fg_attempts IS NOT NULL
                  AND (fg_attempts + COALESCE(ft_attempts, 0)) > 0
                """
            )
        ).scalar()

        if dry_run:
            return {
                "status": "dry_run",
                "efg_rows_pending": efg_pending,
                "ts_rows_pending": ts_pending,
            }

        efg_updated = db.execute(text(EFG_SQL)).rowcount
        ts_updated = db.execute(text(TS_SQL)).rowcount
        db.commit()
        return {
            "status": "ok",
            "efg_rows_updated": efg_updated,
            "ts_rows_updated": ts_updated,
        }
    finally:
        db.close()
