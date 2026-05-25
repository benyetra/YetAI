"""NBA ML training config (delegates to shared ``app.services.ml``)."""

from app.models.predictions_models import RecentGames
from app.services.etl.nba._feature_engineering import build_features
from app.services.ml.config import LeagueMLConfig

# RecentGames maps pred_recent_games (legacy name; spec "NBARecentGames").
NBA_ML_CONFIG = LeagueMLConfig(
    table_prefix="nba",
    s3_prefix="nba/ml_models",
    feature_builder_path="app.services.etl.nba._feature_engineering.build_features",
    feature_builder=build_features,
    recent_games_model=RecentGames,
    mae_gate={
        "points": 5.0,
        "assists": 1.6,
        "rebounds": 2.2,
    },
    supported_stats=("points", "rebounds", "assists"),
)
