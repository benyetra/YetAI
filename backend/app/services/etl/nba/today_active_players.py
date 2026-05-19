"""Populate pred_today_active_players from today's ESPN scoreboard + roster.

Port of YetiBets/scripts/nba/today_active_players_espn.py (Development-1nt).
Behavior preserved: refresh pred_today_active_players for today (Eastern)
from ESPN scoreboard ∩ pred_team_roster. If ESPN returns no games for today
the prior data is left in place — this is a feature of the original.
"""

from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.models.predictions_models import TeamRoster, TodayActivePlayers
from app.services.etl.nba._espn import (
    NBA_TEAM_NAMES,
    build_matchups,
    fetch_games_for_date,
    now_eastern,
)

logger = logging.getLogger(__name__)


def run() -> dict:
    today = now_eastern().date()

    # No date param: ESPN's "today" reflects the live slate which respects
    # ongoing-game state. Matches YetiBets's behavior.
    games = fetch_games_for_date(None)
    if not games:
        logger.info(
            "today_active_players: no NBA games for %s — keeping existing data", today
        )
        return {
            "status": "ok",
            "date": today.isoformat(),
            "games": 0,
            "players": 0,
            "kept_stale": True,
        }

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

        db.query(TodayActivePlayers).delete(synchronize_session=False)

        seen: set[int] = set()
        entries = []
        for player_id, player_name, position, team_id in rows:
            if player_id in seen:
                continue
            seen.add(player_id)
            opponent_team_id = matchups.get(team_id)
            if opponent_team_id is None:
                continue
            entries.append(
                TodayActivePlayers(
                    player_id=player_id,
                    player_name=player_name,
                    position=position,
                    team_id=team_id,
                    team_name=NBA_TEAM_NAMES.get(team_id, "Unknown"),
                    opponent_team_id=opponent_team_id,
                    opponent_team_name=NBA_TEAM_NAMES.get(opponent_team_id, "Unknown"),
                    game_date=today,
                )
            )

        db.bulk_save_objects(entries)
        db.commit()
        logger.info(
            "today_active_players: stored %d players across %d games for %s",
            len(entries),
            len(games),
            today,
        )
        return {
            "status": "ok",
            "date": today.isoformat(),
            "games": len(games),
            "players": len(entries),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
