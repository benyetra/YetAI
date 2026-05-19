"""Populate pred_yesterdays_players from yesterday's ESPN scoreboard + roster.

Port of YetiBets/scripts/nba/yesterdays_players_espn.py (Development-1nt).
Behavior preserved: full-table refresh of pred_yesterdays_players for the
yesterday-Eastern date, derived from ESPN scoreboard ∩ pred_team_roster.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import TeamRoster, YesterdaysPlayers
from app.services.etl.nba._espn import (
    NBA_TEAM_NAMES,
    build_matchups,
    fetch_games_for_date,
    now_eastern,
)

logger = logging.getLogger(__name__)


def run() -> dict:
    yesterday = (now_eastern() - timedelta(days=1)).date()

    games = fetch_games_for_date(yesterday)
    if not games:
        logger.info("yesterdays_players: no NBA games for %s", yesterday)
        return {"status": "ok", "date": yesterday.isoformat(), "games": 0, "players": 0}

    team_ids, matchups = build_matchups(games)

    db = SessionLocal()
    try:
        rows = (
            db.query(
                TeamRoster.player_id,
                TeamRoster.player_name,
                TeamRoster.position,
                TeamRoster.team_id,
            )
            .filter(TeamRoster.team_id.in_(team_ids))
            .all()
        )

        # Full refresh: drop the prior day's data before reinsert. The original
        # script DROP+create_all'd the table; we just DELETE since the schema is
        # owned by Alembic.
        db.query(YesterdaysPlayers).delete(synchronize_session=False)

        entries = []
        for player_id, player_name, position, team_id in rows:
            opponent_team_id = matchups.get(team_id)
            if opponent_team_id is None:
                continue
            entries.append(
                YesterdaysPlayers(
                    player_id=player_id,
                    player_name=player_name,
                    position=position,
                    team_id=team_id,
                    team_name=NBA_TEAM_NAMES.get(team_id, "Unknown"),
                    opponent_team_id=opponent_team_id,
                    opponent_team_name=NBA_TEAM_NAMES.get(opponent_team_id, "Unknown"),
                    game_date=yesterday,
                )
            )

        db.bulk_save_objects(entries)
        db.commit()
        logger.info(
            "yesterdays_players: stored %d players across %d games for %s",
            len(entries),
            len(games),
            yesterday,
        )
        return {
            "status": "ok",
            "date": yesterday.isoformat(),
            "games": len(games),
            "players": len(entries),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
