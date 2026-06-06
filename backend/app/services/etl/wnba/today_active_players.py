"""Populate pred_wnba_today_active_players from today's ESPN scoreboard ∩ roster.

Behavior mirrors NBA today_active_players: refresh today's slate from ESPN
games, intersect with pred_wnba_team_roster. If ESPN returns no games for
today, the prior data is left in place.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import WNBATeamRoster, WNBATodayActivePlayers
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import build_matchups, fetch_games, now_eastern

logger = logging.getLogger(__name__)


def run() -> dict:
    today = now_eastern().date()
    games = fetch_games(today)
    if not games:
        logger.info(
            "today_active_players: no WNBA games for %s — keeping existing rows", today
        )
        return {
            "status": "ok",
            "date": today.isoformat(),
            "games": 0,
            "players": 0,
            "kept_stale": True,
        }

    team_ids, matchups = build_matchups(games)
    if not team_ids:
        return {
            "status": "ok",
            "date": today.isoformat(),
            "games": 0,
            "players": 0,
            "kept_stale": True,
        }

    # Build a per-team-id → opponent + team_name + home/away lookup.
    team_meta: dict[int, dict] = {}
    for m in matchups:
        team_meta[m["home_team_id_wnba"]] = {
            "team_name": m["home_team_name"],
            "opponent_team_id": m["away_team_id_wnba"],
            "opponent_team_name": m["away_team_name"],
            "home_game": True,
        }
        team_meta[m["away_team_id_wnba"]] = {
            "team_name": m["away_team_name"],
            "opponent_team_id": m["home_team_id_wnba"],
            "opponent_team_name": m["home_team_name"],
            "home_game": False,
        }

    db = SessionLocal()
    players_written = 0
    upsert_rows: list[dict] = []
    try:
        roster_rows = (
            db.query(WNBATeamRoster).filter(WNBATeamRoster.team_id.in_(team_ids)).all()
        )
        seen_player_ids: set[int] = set()
        duplicates_skipped = 0
        for r in roster_rows:
            meta = team_meta.get(r.team_id)
            if not meta:
                continue
            if r.player_id in seen_player_ids:
                duplicates_skipped += 1
                continue
            seen_player_ids.add(r.player_id)
            upsert_rows.append(
                {
                    "player_id": r.player_id,
                    "player_name": r.player_name,
                    "team_id": r.team_id,
                    "team_name": meta["team_name"],
                    "opponent_team_id": meta["opponent_team_id"],
                    "opponent_team_name": meta["opponent_team_name"],
                    "game_date": today,
                    "home_game": meta["home_game"],
                    "last_updated": datetime.utcnow(),
                }
            )
            players_written += 1
        if duplicates_skipped:
            logger.warning(
                "today_active_players: skipped %d duplicate player_id roster rows for %s",
                duplicates_skipped,
                today,
            )
        upsert_many(
            db,
            WNBATodayActivePlayers,
            upsert_rows,
            conflict_keys=["player_id", "game_date"],
        )
        db.commit()
        return {
            "status": "ok",
            "date": today.isoformat(),
            "games": len(matchups),
            "players": players_written,
            "duplicates_skipped": duplicates_skipped,
            "kept_stale": False,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
