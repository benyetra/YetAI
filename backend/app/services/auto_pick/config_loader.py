from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.database_models import ScoringConfig
from app.services.auto_pick.scoring_context import ScoringWeights


@dataclass
class LoadedScoringConfig:
    weights: ScoringWeights
    score_threshold: float
    odds_min: int
    odds_max: int
    max_picks: int
    parlay_leg_threshold: float = 55.0
    parlay_score_threshold: float = 55.0


def load_scoring_config(db: Session) -> LoadedScoringConfig:
    row = db.query(ScoringConfig).order_by(ScoringConfig.id.asc()).first()
    if row is None:
        return LoadedScoringConfig(
            weights=ScoringWeights(),
            score_threshold=65.0,
            odds_min=-300,
            odds_max=400,
            max_picks=4,
            parlay_leg_threshold=55.0,
            parlay_score_threshold=55.0,
        )
    return LoadedScoringConfig(
        weights=ScoringWeights(
            edge=row.weight_edge,
            historical=row.weight_historical,
            freshness=row.weight_freshness,
            line_movement=row.weight_line_movement,
            odds_sanity=row.weight_odds_sanity,
            model_conf=row.weight_model_conf,
        ),
        score_threshold=row.score_threshold,
        odds_min=row.odds_min,
        odds_max=row.odds_max,
        max_picks=row.max_picks_per_day,
    )
