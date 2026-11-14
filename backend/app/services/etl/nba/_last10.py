"""Last-10-games average projection for threes, steals, blocks, free throws.

These four stats were served by static XGBoost models (S3, no training code).
On correctly dated box scores each is worse than a plain average of the
player's recent games (MAE model vs average, this season's projection rows):
threes 1.006 vs 0.932, steals 0.746 vs 0.729, blocks 0.569 vs 0.545,
free throws 1.513 vs 1.465.

Rule: take the player's latest 10 games before `before` with a non-null value
for the stat. If at least 5 are from the current season, average only those;
otherwise average all of them (last season fills in). Under 5 games in total
-> None (the generator skips the player).

Switch: env NBA_LAST10_PROPS=0/false/off restores the S3 models (default ON).
"""

from __future__ import annotations

import os
from datetime import date

from app.models.predictions_models import RecentGames
from app.services.etl.nba._season import season_opener

LAST10_STATS = frozenset({"three_pt_made", "steals", "blocks", "free_throws_made"})
LAST10_MODEL_VERSION = "last10-avg-v1"
_WINDOW = 10
_MIN_GAMES = 5


def enabled(stat: str) -> bool:
    if stat not in LAST10_STATS:
        return False
    return os.getenv("NBA_LAST10_PROPS", "").strip().lower() not in {
        "0",
        "false",
        "off",
    }


def projection(db, player_id: int, before: date, stat: str) -> float | None:
    col = getattr(RecentGames, stat)
    rows = (
        db.query(RecentGames.game_date, col)
        .filter(
            RecentGames.player_id == player_id,
            RecentGames.game_date < before,
            col.isnot(None),
        )
        .order_by(RecentGames.game_date.desc())
        .limit(_WINDOW)
        .all()
    )
    if len(rows) < _MIN_GAMES:
        return None
    opener = season_opener(before)
    current = [v for d, v in rows if d >= opener]
    use = current if len(current) >= _MIN_GAMES else [v for _, v in rows]
    return sum(use) / len(use)
