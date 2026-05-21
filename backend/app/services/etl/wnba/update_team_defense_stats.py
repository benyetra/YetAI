"""Refresh pred_wnba_team_defense_stats from stats.wnba.com.

Joins Base + Defense + Advanced dashboards on TEAM_ID and upserts to
pred_wnba_team_defense_stats. Mirrors NBA update_team_defense_stats.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import WNBATeamDefenseStats
from app.services.etl.wnba import _wnba_stats
from app.services.etl.wnba._espn import now_eastern

logger = logging.getLogger(__name__)


def _current_season() -> str:
    return str(now_eastern().year)


def run(season: str | None = None) -> dict:
    season = season or _current_season()
    base = _wnba_stats.fetch_team_dashboard(season=season, measure_type="Base")
    defense = _wnba_stats.fetch_team_dashboard(season=season, measure_type="Defense")
    advanced = _wnba_stats.fetch_team_dashboard(season=season, measure_type="Advanced")

    base_by_id = {row["TEAM_ID"]: row for row in base}
    advanced_by_id = {row["TEAM_ID"]: row for row in advanced}

    db = SessionLocal()
    try:
        for row in defense:
            team_id = int(row["TEAM_ID"])
            b = base_by_id.get(team_id, {})
            adv = advanced_by_id.get(team_id, {})
            obj = WNBATeamDefenseStats(
                team_id=team_id,
                team_name=row.get("TEAM_NAME") or b.get("TEAM_NAME"),
                points_allowed_per_game=row.get("OPP_PTS"),
                assists_allowed_per_game=row.get("OPP_AST"),
                rebounds_allowed_per_game=row.get("OPP_REB"),
                offensive_rebounds_allowed_per_game=row.get("OPP_OREB"),
                defensive_rebounds=b.get("DREB"),
                field_goal_pct_allowed=row.get("OPP_FG_PCT"),
                three_pt_pct_allowed=row.get("OPP_FG3_PCT"),
                three_pt_made_allowed_per_game=row.get("OPP_FG3M"),
                three_pt_attempted_allowed_per_game=row.get("OPP_FG3A"),
                free_throws_allowed_per_game=row.get("OPP_FTM"),
                turnovers=row.get("OPP_TOV"),
                steals=b.get("STL"),
                blocks=b.get("BLK"),
                personal_fouls=b.get("PF"),
                pace=adv.get("PACE"),
                defensive_rating=adv.get("DEF_RATING"),
                last_updated=datetime.utcnow(),
            )
            db.merge(obj)
        db.commit()
        return {"status": "ok", "season": season, "teams": len(defense)}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
