"""Which of a player's box scores the NBA projections sample from.

Once a player has any games this season, only this season's games count:
trades, rotations and roles change over the summer, so last season's lines
describe a different player (a rebuilding team's young players who ran up
minutes in a lost March, for one). Last season is a stand-in only when the
player has not appeared yet (opening night, a season-long absence).
"""

from __future__ import annotations

from datetime import date

from app.models.predictions_models import RecentGames
from app.services.etl.nba._season import season_opener

# Use this season as soon as it exists. Last season is only the stand-in
# when the player or team has zero current-season games.
MIN_CURRENT_SEASON_GAMES = 1


def player_games(
    db,
    player_id: int,
    before: date,
    limit: int,
    *criteria,
    min_current: int = MIN_CURRENT_SEASON_GAMES,
) -> list:
    """The player's last `limit` games before `before`, newest first.

    This season's games are used when there are at least min(limit, min_current)
    of them; otherwise last season fills in."""
    query = (
        db.query(RecentGames)
        .filter(
            RecentGames.player_id == player_id,
            RecentGames.game_date < before,
            *criteria,
        )
        .order_by(RecentGames.game_date.desc())
    )
    current = (
        query.filter(RecentGames.game_date >= season_opener(before)).limit(limit).all()
    )
    if len(current) >= min(limit, min_current):
        return current
    return query.limit(limit).all()


def current_season_games(db, player_id: int, before: date) -> int:
    """How many games the player has played this season before `before`."""
    return (
        db.query(RecentGames)
        .filter(
            RecentGames.player_id == player_id,
            RecentGames.game_date < before,
            RecentGames.game_date >= season_opener(before),
        )
        .count()
    )
