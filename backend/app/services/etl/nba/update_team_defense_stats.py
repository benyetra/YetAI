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

from app.core.database import SessionLocal
from app.models.predictions_models import TeamDefenseStats
from app.services.etl.nba._espn import EASTERN, NBA_TEAM_NAMES, now_eastern
from app.services.etl.nba._team_defense import (  # noqa: F401 - re-exported
    LEAGUE_AVG_DRTG,
    LEAGUE_AVG_TRACKED_PTS,
    LOOKBACK_GAMES,
    team_defense_as_of,
)

logger = logging.getLogger(__name__)


def run() -> dict:
    end_date = now_eastern().date()
    teams_updated = 0
    teams_no_data = 0

    db = SessionLocal()
    try:
        for nba_team_id, team_name in NBA_TEAM_NAMES.items():
            # Everything played through today: the same numbers the feature
            # builder computes for tomorrow's games (see _team_defense).
            stats = team_defense_as_of(db, nba_team_id, end_date + timedelta(days=1))
            if stats is None:
                teams_no_data += 1
                continue
            data = {k: v for k, v in stats.items() if k != "games"}
            data["team_name"] = team_name
            data["last_updated"] = datetime.now(EASTERN)

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
            "lookback_games": LOOKBACK_GAMES,
            "teams_updated": teams_updated,
            "teams_no_data": teams_no_data,
        }
    finally:
        db.close()
