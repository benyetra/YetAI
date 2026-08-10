"""Store completed NFL REG game scores and refresh Elo snapshot.

v1 uses nflverse REG finals only (no ESPN scoreboard). The pilot spec allowed
either source; we standardize on nflverse for parity with ``seed_elo_history``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NFLSpreadActuals,
    NFLTeamElo,
    NFLTotalsActuals,
    NFLTotalsProjections,
)
from app.services.etl._spread_model import NFL_CONFIG, load_elos_from_actuals
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nfl.nfl_common import get_nfl_season
from app.services.etl.nfl.seed_elo import fetch_reg_games_nflverse
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 14


def fetch_recent_completed_reg_games(
    seasons: list[int] | None = None,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    today: date | None = None,
) -> list[SimpleNamespace]:
    """Completed REG games within the lookback window (mockable in tests)."""
    ref = today if today is not None else now_eastern().date()
    cutoff = ref - timedelta(days=lookback_days)
    resolved = list(seasons if seasons is not None else [get_nfl_season()])
    games = fetch_reg_games_nflverse(resolved)
    recent: list[SimpleNamespace] = []
    for game in games:
        game_date = getattr(game, "game_date", None)
        if game_date is None:
            continue
        if cutoff <= game_date <= ref:
            recent.append(game)
    return recent


def _spread_actual_row(game: SimpleNamespace) -> dict:
    home_score = int(game.home_score)
    away_score = int(game.away_score)
    return {
        "game_date": game.game_date,
        "home_team_name": game.home_team_name,
        "away_team_name": game.away_team_name,
        "home_score": home_score,
        "away_score": away_score,
        "actual_margin": home_score - away_score,
        "home_won": home_score > away_score,
        "created_at": datetime.utcnow(),
    }


def _totals_actual_row(
    game: SimpleNamespace, projection: NFLTotalsProjections | None
) -> dict:
    home_score = int(game.home_score)
    away_score = int(game.away_score)
    actual_total = home_score + away_score
    projected_total = projection.projected_total if projection else None
    market_total = projection.market_total if projection else None
    was_over = None
    correct_prediction = None
    if market_total is not None:
        was_over = actual_total > market_total
    if (
        projection
        and projection.recommendation in ("OVER", "UNDER")
        and market_total is not None
    ):
        correct_prediction = (projection.recommendation == "OVER" and was_over) or (
            projection.recommendation == "UNDER" and not was_over
        )
    return {
        "game_date": game.game_date,
        "home_team_id": projection.home_team_id if projection else None,
        "away_team_id": projection.away_team_id if projection else None,
        "home_team_name": game.home_team_name,
        "away_team_name": game.away_team_name,
        "actual_total": actual_total,
        "home_actual_score": home_score,
        "away_actual_score": away_score,
        "projected_total": projected_total,
        "market_total": market_total,
        "projection_error": (
            round(actual_total - projected_total, 1)
            if projected_total is not None
            else None
        ),
        "market_error": (
            round(actual_total - market_total, 1) if market_total is not None else None
        ),
        "was_over": was_over,
        "correct_prediction": correct_prediction,
        "created_at": datetime.utcnow(),
    }


def upsert_spread_and_totals_actuals(
    db, games: list[SimpleNamespace]
) -> tuple[int, int]:
    """Upsert spread/totals actual rows for completed games."""
    if not games:
        return 0, 0

    spread_rows: list[dict] = []
    totals_rows: list[dict] = []
    for game in games:
        if getattr(game, "game_date", None) is None:
            continue
        spread_rows.append(_spread_actual_row(game))
        projection = (
            db.query(NFLTotalsProjections)
            .filter_by(
                game_date=game.game_date,
                home_team_name=game.home_team_name,
                away_team_name=game.away_team_name,
            )
            .first()
        )
        totals_rows.append(_totals_actual_row(game, projection))

    if spread_rows:
        upsert_many(
            db,
            NFLSpreadActuals,
            spread_rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
    if totals_rows:
        upsert_many(
            db,
            NFLTotalsActuals,
            totals_rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
    return len(spread_rows), len(totals_rows)


def upsert_team_elo_snapshot(db, elos: dict[str, float], as_of: date) -> dict:
    """Persist computed team Elos into pred_nfl_team_elo."""
    if not elos:
        return {"teams": 0}

    now = datetime.utcnow()
    rows = [
        {
            "team_name": team_name,
            "elo": elo,
            "as_of_date": as_of,
            "updated_at": now,
        }
        for team_name, elo in elos.items()
    ]
    upsert_many(db, NFLTeamElo, rows, conflict_keys=["team_name"])
    return {"teams": len(rows), "as_of_date": as_of.isoformat()}


def refresh_team_elo_snapshot(db) -> dict:
    """Rebuild pred_nfl_team_elo from chronological spread actuals."""
    actuals = (
        db.query(NFLSpreadActuals).order_by(NFLSpreadActuals.game_date.asc()).all()
    )
    if not actuals:
        return {"teams": 0}

    elos = load_elos_from_actuals(actuals, cfg=NFL_CONFIG)
    as_of = max(row.game_date for row in actuals)
    return upsert_team_elo_snapshot(db, elos, as_of)


def run(*, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict:
    """Persist recent finals, then refresh the Elo snapshot."""
    seasons = [get_nfl_season()]
    games = fetch_recent_completed_reg_games(seasons, lookback_days=lookback_days)

    db = SessionLocal()
    try:
        spread_n, totals_n = upsert_spread_and_totals_actuals(db, games)
        elo_stats = refresh_team_elo_snapshot(db)
        db.commit()
        return {
            "status": "ok",
            "games_seen": len(games),
            "spread_actuals_upserted": spread_n,
            "totals_actuals_upserted": totals_n,
            **elo_stats,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
