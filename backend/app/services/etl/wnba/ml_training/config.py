"""WNBA ML training config (delegates to shared ``app.services.ml``)."""

from app.models.predictions_models import WNBARecentGames

# Holdout residual MAE gate for totals GBM upload (time-based split).
TOTALS_RESIDUAL_MAE_GATE = 1.0
from app.services.etl.wnba._feature_engineering import build_features
from app.services.ml.config import LeagueMLConfig

# Supersedes YetAI-2wf: league constants live here; logic is in app.services.ml.
WNBA_ML_CONFIG = LeagueMLConfig(
    table_prefix="wnba",
    s3_prefix="wnba/ml_models",
    feature_builder_path="app.services.etl.wnba._feature_engineering.build_features",
    feature_builder=build_features,
    recent_games_model=WNBARecentGames,
    mae_gate={
        "points": 4.5,
        "assists": 1.5,
        "rebounds": 2.0,
    },
    supported_stats=("points", "assists", "rebounds"),
)
