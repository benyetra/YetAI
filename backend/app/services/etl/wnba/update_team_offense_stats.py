"""Refresh pred_wnba_team_offense_stats from stats.wnba.com."""

from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.models.predictions_models import WNBATeamOffenseStats
from app.services.etl.wnba import _wnba_stats
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import now_eastern

logger = logging.getLogger(__name__)


def _current_season() -> str:
    return str(now_eastern().year)


def run(season: str | None = None) -> dict:
    season = season or _current_season()
    base = _wnba_stats.fetch_team_dashboard(season=season, measure_type="Base")
    advanced = _wnba_stats.fetch_team_dashboard(season=season, measure_type="Advanced")
    advanced_by_id = {row["TEAM_ID"]: row for row in advanced}

    upsert_rows = []
    for row in base:
        team_id = int(row["TEAM_ID"])
        adv = advanced_by_id.get(team_id, {})
        upsert_rows.append(
            {
                "team_id": team_id,
                "team_name": row["TEAM_NAME"],
                "games_played": row.get("GP"),
                "turnovers_per_game": row.get("TOV"),
                "pace": adv.get("PACE"),
                "points_per_game": row.get("PTS"),
                "assists_per_game": row.get("AST"),
                "offensive_rebounds_per_game": row.get("OREB"),
                "field_goals_made_per_game": row.get("FGM"),
                "field_goal_percentage": row.get("FG_PCT"),
                "three_point_percentage": row.get("FG3_PCT"),
            }
        )

    db = SessionLocal()
    try:
        upsert_many(db, WNBATeamOffenseStats, upsert_rows, conflict_keys=["team_id"])
        db.commit()
        return {"status": "ok", "season": season, "teams": len(base)}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
