"""WNBA spread / win-probability projector.

Primary: XGBoost margin model when S3 artifact is present (player-availability features).
Fallback: Elo + pace/efficiency overlay (Plan A).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAGameLines,
    WNBASpreadActuals,
    WNBASpreadProjections,
    WNBATeamDefenseStats,
    WNBATeamOffenseStats,
)
from app.services.etl import _spread_model as _sm
from app.services.etl._spread_model import (
    WNBA_CONFIG,
    load_elos_from_actuals,
    spread_recommendation,
)
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba._spread_features import build_game_features
from app.services.etl.wnba._spread_ml_predict import model_available, predict_margin

logger = logging.getLogger(__name__)

# Re-export for tests that import constants from this module.
INITIAL_ELO = WNBA_CONFIG.initial_elo
ELO_K = WNBA_CONFIG.elo_k
HOME_COURT_ADVANTAGE = WNBA_CONFIG.home_court_advantage
SPREAD_PER_ELO = WNBA_CONFIG.spread_per_elo
WIN_PROB_LOGISTIC_SCALE = WNBA_CONFIG.win_prob_logistic_scale
EDGE_THRESHOLD = WNBA_CONFIG.edge_threshold


def update_elo(
    home_elo: float, away_elo: float, home_score: int, away_score: int
) -> tuple[float, float]:
    return _sm.update_elo(home_elo, away_elo, home_score, away_score, cfg=WNBA_CONFIG)


def expected_margin(home_elo: float, away_elo: float) -> float:
    return _sm.expected_margin(home_elo, away_elo, cfg=WNBA_CONFIG)


def margin_to_win_prob(margin: float) -> float:
    return _sm.margin_to_win_prob(margin, cfg=WNBA_CONFIG)


def pace_overlay_adjustment(
    home_off: float | None,
    home_def: float | None,
    away_off: float | None,
    away_def: float | None,
) -> float:
    return _sm.pace_overlay_adjustment(
        home_off, home_def, away_off, away_def, cfg=WNBA_CONFIG
    )


def _load_elos(db) -> dict[str, float]:
    actuals = (
        db.query(WNBASpreadActuals).order_by(WNBASpreadActuals.game_date.asc()).all()
    )
    return load_elos_from_actuals(actuals, cfg=WNBA_CONFIG)


def run() -> dict:
    today = now_eastern().date()
    end = today + timedelta(days=1)
    use_ml = model_available()

    db = SessionLocal()
    upsert_rows: list[dict] = []
    try:
        elos = _load_elos(db)
        offense_by_name = {o.team_name: o for o in db.query(WNBATeamOffenseStats).all()}
        defense_by_name = {d.team_name: d for d in db.query(WNBATeamDefenseStats).all()}

        games = (
            db.query(WNBAGameLines)
            .filter(WNBAGameLines.game_date >= today, WNBAGameLines.game_date <= end)
            .all()
        )

        for g in games:
            home_elo = elos.get(g.home_team_name, INITIAL_ELO)
            away_elo = elos.get(g.away_team_name, INITIAL_ELO)
            base_margin = expected_margin(home_elo, away_elo)

            home_off = offense_by_name.get(g.home_team_name)
            home_def = defense_by_name.get(g.home_team_name)
            away_off = offense_by_name.get(g.away_team_name)
            away_def = defense_by_name.get(g.away_team_name)
            pace_adj = pace_overlay_adjustment(
                home_off.points_per_game if home_off else None,
                home_def.points_allowed_per_game if home_def else None,
                away_off.points_per_game if away_off else None,
                away_def.points_allowed_per_game if away_def else None,
            )

            projection_method = "elo_pace"
            projected_margin = base_margin + pace_adj

            if use_ml:
                feats = build_game_features(
                    db,
                    game_date=g.game_date,
                    home_team_name=g.home_team_name,
                    away_team_name=g.away_team_name,
                    home_team_id=g.home_team_id,
                    away_team_id=g.away_team_id,
                    market_spread_home=g.spread_home,
                    market_total=g.total,
                    spread_actuals_model=WNBASpreadActuals,
                )
                if feats is not None:
                    ml_margin = predict_margin(feats)
                    if ml_margin is not None:
                        projected_margin = ml_margin
                        projection_method = "ml"

            home_win_prob = margin_to_win_prob(projected_margin)
            edge, recommendation = spread_recommendation(
                projected_margin, g.spread_home, cfg=WNBA_CONFIG
            )

            upsert_rows.append(
                {
                    "game_date": g.game_date,
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "home_team_name": g.home_team_name,
                    "away_team_name": g.away_team_name,
                    "projected_margin": projected_margin,
                    "home_win_prob": home_win_prob,
                    "home_elo": home_elo,
                    "away_elo": away_elo,
                    "home_court_advantage": HOME_COURT_ADVANTAGE,
                    "pace_adjustment": pace_adj,
                    "market_spread_home": g.spread_home,
                    "edge": edge,
                    "recommendation": recommendation,
                    "confidence_score": (
                        min(1.0, abs(edge) / 6.0) if edge is not None else None
                    ),
                    "factors": {
                        "elo_diff": home_elo - away_elo,
                        "pace_adj": pace_adj,
                        "method": projection_method,
                    },
                    "created_at": datetime.utcnow(),
                }
            )
        upsert_many(
            db,
            WNBASpreadProjections,
            upsert_rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
        db.commit()
        return {
            "status": "ok",
            "games": len(upsert_rows),
            "projection_method": "ml" if use_ml else "elo_pace",
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
