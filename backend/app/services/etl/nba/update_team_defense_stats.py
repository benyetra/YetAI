"""Derive pred_team_defense_stats from pred_recent_games (Development-1nt).

Port of YetiBets/scripts/nba/update_team_defense_stats_api_sports.py. Despite
the source filename, this script doesn't actually call api-sports — it
aggregates over RecentGames where each team appears as the opponent, gives
"what opponents scored against you" per-game averages. Pure SQL.

Defensive rating is a rough scale of points_allowed_per_game against the
tracked-data league average — the original noted this is imperfect because
RecentGames only tracks individual player lines, not full team totals.
Preserved as-is for parity.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.predictions_models import RecentGames, TeamDefenseStats
from app.services.etl.nba._espn import EASTERN, NBA_TEAM_NAMES, now_eastern

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 60
LEAGUE_AVG_DRTG = 114.0
LEAGUE_AVG_TRACKED_PTS = 95.0


def run() -> dict:
    end_date = now_eastern().date()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)
    teams_updated = 0
    teams_no_data = 0

    db = SessionLocal()
    try:
        for nba_team_id, team_name in NBA_TEAM_NAMES.items():
            base_filter = [
                RecentGames.opponent_team_id == nba_team_id,
                RecentGames.game_date >= start_date,
                RecentGames.game_date <= end_date,
            ]

            games_as_opp = (
                db.query(func.count(func.distinct(RecentGames.game_date)))
                .filter(*base_filter)
                .scalar()
            ) or 0
            if not games_as_opp:
                teams_no_data += 1
                continue

            totals = (
                db.query(
                    func.sum(RecentGames.points).label("points"),
                    func.sum(RecentGames.assists).label("assists"),
                    func.sum(RecentGames.rebounds).label("rebounds"),
                    func.sum(RecentGames.offensive_rebounds).label("oreb"),
                    func.sum(RecentGames.defensive_rebounds).label("dreb"),
                    func.sum(RecentGames.three_pt_made).label("tpm"),
                    func.sum(RecentGames.three_pt_attempts).label("tpa"),
                    func.sum(RecentGames.free_throws_made).label("ftm"),
                    func.sum(RecentGames.steals).label("steals"),
                    func.sum(RecentGames.blocks).label("blocks"),
                    func.sum(RecentGames.turnovers).label("turnovers"),
                    func.sum(RecentGames.personal_fouls).label("fouls"),
                    func.avg(RecentGames.fg_percentage).label("avg_fg_pct"),
                )
                .filter(*base_filter)
                .first()
            )

            def per_game(value):
                return round((value or 0) / games_as_opp, 1)

            data = {
                "team_name": team_name,
                "points_allowed_per_game": per_game(totals.points),
                "assists_allowed_per_game": per_game(totals.assists),
                "rebounds_allowed_per_game": per_game(totals.rebounds),
                "offensive_rebounds_allowed_per_game": per_game(totals.oreb),
                "defensive_rebounds": per_game(totals.dreb),
                "three_pt_made_allowed_per_game": per_game(totals.tpm),
                "three_pt_attempted_allowed_per_game": per_game(totals.tpa),
                "free_throws_allowed_per_game": per_game(totals.ftm),
                "steals": per_game(totals.steals),
                "blocks": per_game(totals.blocks),
                "turnovers": per_game(totals.turnovers),
                "personal_fouls": per_game(totals.fouls),
                "last_updated": datetime.now(EASTERN),
            }
            if totals.tpa and totals.tpa > 0:
                data["three_pt_pct_allowed"] = round((totals.tpm or 0) / totals.tpa, 3)
            if totals.avg_fg_pct:
                data["field_goal_pct_allowed"] = round(float(totals.avg_fg_pct), 3)

            pts_tracked = data["points_allowed_per_game"]
            if pts_tracked > 0:
                relative = pts_tracked / LEAGUE_AVG_TRACKED_PTS
                data["defensive_rating"] = round(LEAGUE_AVG_DRTG * relative, 1)
            else:
                data["defensive_rating"] = LEAGUE_AVG_DRTG

            existing = db.query(TeamDefenseStats).filter_by(team_id=nba_team_id).first()
            try:
                if existing:
                    for k, v in data.items():
                        setattr(existing, k, v)
                else:
                    db.add(TeamDefenseStats(team_id=nba_team_id, **data))
                db.commit()
                teams_updated += 1
            except Exception:
                logger.exception("update_team_defense_stats: failed for %s", team_name)
                db.rollback()

        return {
            "status": "ok",
            "lookback_days": LOOKBACK_DAYS,
            "teams_updated": teams_updated,
            "teams_no_data": teams_no_data,
        }
    finally:
        db.close()
