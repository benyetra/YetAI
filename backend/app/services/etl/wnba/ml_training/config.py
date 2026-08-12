"""WNBA ML training config (delegates to shared ``app.services.ml``)."""

from app.models.predictions_models import WNBARecentGames
from app.services.etl.wnba._feature_engineering import build_features
from app.services.ml.config import LeagueMLConfig

# Holdout residual MAE gate for totals GBM upload (time-based split).
TOTALS_RESIDUAL_MAE_GATE = 1.0

# Spread margin XGB upload gates (random 20% holdout from train_model).
# Current overfit artifact (~11.4 test MAE) must fail; Elo+pace remains fallback.
SPREAD_MAE_GATE = 9.0
SPREAD_BRIER_GATE = 0.28

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
        "three_pt_made": 1.0,
    },
    supported_stats=("points", "assists", "rebounds", "three_pt_made"),
)
