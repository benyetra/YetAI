"""NFL spread / win-probability projector (Elo + PPG overlay)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NFLGameLines,
    NFLSpreadActuals,
    NFLSpreadProjections,
    NFLTeamElo,
)
from app.services.etl import _spread_model as _sm
from app.services.etl._spread_model import (
    NFL_CONFIG,
    load_elos_from_actuals,
    spread_recommendation,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nfl._team_ppg import compute_team_ppg_stats, team_ppg_for
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

INITIAL_ELO = NFL_CONFIG.initial_elo
HOME_COURT_ADVANTAGE = NFL_CONFIG.home_court_advantage


def _load_elos(db) -> dict[str, float]:
    stored = db.query(NFLTeamElo).all()
    if stored:
        return {row.team_name: float(row.elo) for row in stored}

    actuals = (
        db.query(NFLSpreadActuals).order_by(NFLSpreadActuals.game_date.asc()).all()
    )
    if actuals:
        return load_elos_from_actuals(actuals, cfg=NFL_CONFIG)
    return {}


def _project_spread_row(
    *,
    home_team_name: str,
    away_team_name: str,
    spread_home: float | None,
    elos: dict[str, float],
    ppg_stats: dict[str, tuple[float, float]],
) -> dict:
    home_elo = elos.get(home_team_name, INITIAL_ELO)
    away_elo = elos.get(away_team_name, INITIAL_ELO)
    base_margin = _sm.expected_margin(home_elo, away_elo, cfg=NFL_CONFIG)

    home_off, home_def = team_ppg_for(home_team_name, ppg_stats)
    away_off, away_def = team_ppg_for(away_team_name, ppg_stats)
    pace_adj = _sm.pace_overlay_adjustment(
        home_off, home_def, away_off, away_def, cfg=NFL_CONFIG
    )

    projected_margin = base_margin + pace_adj
    home_win_prob = _sm.margin_to_win_prob(projected_margin, cfg=NFL_CONFIG)
    edge, recommendation = spread_recommendation(
        projected_margin, spread_home, cfg=NFL_CONFIG
    )

    return {
        "projected_margin": projected_margin,
        "home_win_prob": home_win_prob,
        "home_elo": home_elo,
        "away_elo": away_elo,
        "home_court_advantage": HOME_COURT_ADVANTAGE,
        "pace_adjustment": pace_adj,
        "market_spread_home": spread_home,
        "edge": edge,
        "recommendation": recommendation,
        "confidence_score": min(1.0, abs(edge) / 6.0) if edge is not None else None,
        "factors": {
            "elo_diff": home_elo - away_elo,
            "pace_adj": pace_adj,
            "elo_pace_margin": projected_margin,
            "method": "elo_pace",
        },
    }


def run() -> dict:
    today = now_eastern().date()
    end = today + timedelta(days=1)

    db = SessionLocal()
    upsert_rows: list[dict] = []
    try:
        elos = _load_elos(db)
        actuals = (
            db.query(NFLSpreadActuals).order_by(NFLSpreadActuals.game_date.asc()).all()
        )
        ppg_stats = compute_team_ppg_stats(actuals)

        games = (
            db.query(NFLGameLines)
            .filter(NFLGameLines.game_date >= today, NFLGameLines.game_date <= end)
            .all()
        )

        for g in games:
            projection = _project_spread_row(
                home_team_name=g.home_team_name,
                away_team_name=g.away_team_name,
                spread_home=g.spread_home,
                elos=elos,
                ppg_stats=ppg_stats,
            )
            upsert_rows.append(
                {
                    "game_date": g.game_date,
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "home_team_name": g.home_team_name,
                    "away_team_name": g.away_team_name,
                    "created_at": datetime.utcnow(),
                    **projection,
                }
            )

        upsert_many(
            db,
            NFLSpreadProjections,
            upsert_rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
        db.commit()
        return {
            "status": "ok",
            "games": len(upsert_rows),
            "projection_method": "elo_pace",
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
