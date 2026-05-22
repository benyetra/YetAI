from datetime import date
from unittest.mock import MagicMock

from app.models.predictions_models import WNBASpreadActuals
from app.services.etl.wnba._spread_features import build_game_features


def test_build_game_features_returns_dict():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
        []
    )
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.all.return_value = []

    feats = build_game_features(
        db,
        game_date=date(2026, 5, 21),
        home_team_name="New York Liberty",
        away_team_name="Las Vegas Aces",
        home_team_id=1,
        away_team_id=2,
        market_spread_home=-2.5,
        market_total=162.5,
        spread_actuals_model=WNBASpreadActuals,
    )
    assert feats is not None
    assert "elo_diff" in feats
    assert "minutes_diff" in feats
