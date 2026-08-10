"""One-off Elo seed from nflverse REG history (2023–2025)."""

from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.services.etl.nfl.seed_elo import (
    DEFAULT_SEED_SEASONS,
    fetch_reg_games_nflverse,
    seed_elos_from_games,
)
from app.services.etl.nfl.store_game_actuals import (
    refresh_team_elo_snapshot,
    upsert_spread_and_totals_actuals,
)

logger = logging.getLogger(__name__)


def run(
    seasons: list[int] | None = None,
    *,
    write_actuals: bool = True,
) -> dict:
    """Load historical REG games, optionally write actuals, upsert Elo snapshot."""
    resolved = list(seasons if seasons is not None else DEFAULT_SEED_SEASONS)
    games = fetch_reg_games_nflverse(resolved)
    games_with_dates = [g for g in games if getattr(g, "game_date", None) is not None]

    db = SessionLocal()
    try:
        spread_n = totals_n = 0
        if write_actuals and games_with_dates:
            spread_n, totals_n = upsert_spread_and_totals_actuals(db, games_with_dates)
        elo_stats = refresh_team_elo_snapshot(db)
        db.commit()
    finally:
        db.close()

    elos = seed_elos_from_games(games)
    return {
        "status": "ok",
        "seasons": resolved,
        "games_loaded": len(games),
        "games_with_dates": len(games_with_dates),
        "spread_actuals_upserted": spread_n,
        "totals_actuals_upserted": totals_n,
        "seed_teams": len(elos),
        **elo_stats,
    }


if __name__ == "__main__":
    print(run())
