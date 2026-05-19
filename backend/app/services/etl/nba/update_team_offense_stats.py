"""Refresh pred_team_offense_stats from API-Sports team statistics (Development-1nt).

Port of YetiBets/scripts/nba/update_team_offense_stats_api_sports.py. Calls
/teams/statistics per team for the current season, computes per-game averages
and a rough pace estimate, upserts into pred_team_offense_stats keyed by NBA.com
team_id.
"""

from __future__ import annotations

import logging
import time

from app.core.database import SessionLocal
from app.models.predictions_models import TeamOffenseStats
from app.services.etl.nba._api_sports import (
    API_SPORTS_TO_NBA,
    api_request,
    get_current_season,
)

logger = logging.getLogger(__name__)


def run() -> dict:
    season = get_current_season()
    teams_data = api_request("teams", params={"league": "standard"})
    if not teams_data or not teams_data.get("response"):
        return {"status": "error", "reason": "failed_to_fetch_teams"}

    teams = teams_data["response"]
    teams_updated = 0
    teams_no_data = 0

    db = SessionLocal()
    try:
        for team in teams:
            api_team_id = team["id"]
            nba_team_id = API_SPORTS_TO_NBA.get(api_team_id)
            if not nba_team_id:
                continue
            team_name = team.get("name", "Unknown")

            stats_data = api_request(
                "teams/statistics", params={"id": api_team_id, "season": season}
            )
            if not stats_data or not stats_data.get("response"):
                teams_no_data += 1
                continue

            stats = stats_data["response"]
            team_stats = stats[0] if isinstance(stats, list) else stats
            games = team_stats.get("games", 0) or 0
            if not games:
                teams_no_data += 1
                continue

            try:
                ppg = team_stats.get("points", 0) / games
                fgm = team_stats.get("fgm", 0) / games
                fga = team_stats.get("fga", 0) / games
                ast = team_stats.get("assists", 0) / games
                oreb = team_stats.get("offReb", 0) / games
                tov = team_stats.get("turnovers", 0) / games
                fta = team_stats.get("fta", 0) / games
                fg_pct = float(team_stats.get("fgp") or 0) / 100
                three_pct = float(team_stats.get("tpp") or 0) / 100
                pace = fga + 0.44 * fta - oreb + tov

                payload = {
                    "team_name": team_name,
                    "games_played": games,
                    "points_per_game": round(ppg, 1),
                    "field_goals_made_per_game": round(fgm, 1),
                    "field_goal_percentage": round(fg_pct, 3),
                    "three_point_percentage": round(three_pct, 3),
                    "assists_per_game": round(ast, 1),
                    "offensive_rebounds_per_game": round(oreb, 1),
                    "turnovers_per_game": round(tov, 1),
                    "pace": round(pace, 1),
                }
                existing = (
                    db.query(TeamOffenseStats)
                    .filter_by(team_id=nba_team_id)
                    .first()
                )
                if existing:
                    for k, v in payload.items():
                        setattr(existing, k, v)
                else:
                    db.add(TeamOffenseStats(team_id=nba_team_id, **payload))
                db.commit()
                teams_updated += 1
            except Exception:
                logger.exception("update_team_offense_stats: failed for %s", team_name)
                db.rollback()
            time.sleep(0.2)

        return {
            "status": "ok",
            "season": season,
            "teams_updated": teams_updated,
            "teams_no_data": teams_no_data,
        }
    finally:
        db.close()
