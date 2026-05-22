from datetime import date, timedelta
from unittest.mock import MagicMock

from app.services.etl.wnba import _feature_engineering as fe


def _mk_recent_game(d, **stats):
    g = MagicMock()
    g.game_date = d
    for k, v in stats.items():
        setattr(g, k, v)
    # default stats not provided
    for k in (
        "minutes",
        "points",
        "assists",
        "rebounds",
        "usage_percentage",
        "true_shooting_percentage",
    ):
        if not hasattr(g, k) or getattr(g, k) is None:
            if k not in stats:
                setattr(g, k, 0.0)
    g.opponent_team_id = stats.get("opponent_team_id", 999)
    return g


def test_l3_l5_l10_averages_computed():
    today = date(2026, 6, 15)
    games = [
        _mk_recent_game(
            today - timedelta(days=i),
            points=10 + i,
            assists=2 + i,
            rebounds=5 + i,
            minutes=30,
        )
        for i in range(10)
    ]
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
        games
    )
    # Stub opponent defense
    db.query.return_value.filter.return_value.first.return_value = MagicMock(
        points_allowed_per_game=80.0,
        defensive_rating=100.0,
        pace=80.0,
        assists_allowed_per_game=18.0,
        rebounds_allowed_per_game=33.0,
    )

    feats = fe.build_features(
        db, stat_col="points", player_id=100, game_date=today, opponent_team_id=999
    )

    # L3 = (10,11,12)/3 = 11; L5 = (10..14)/5 = 12; L10 = (10..19)/10 = 14.5
    assert feats["points_l3"] == 11.0
    assert feats["points_l5"] == 12.0
    assert feats["points_l10"] == 14.5
    # Opponent context present
    assert feats["opp_points_allowed_per_game"] == 80.0
    assert feats["opp_defensive_rating"] == 100.0


def test_insufficient_history_returns_none():
    today = date(2026, 6, 15)
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        _mk_recent_game(today - timedelta(days=1), points=10, minutes=30)
    ]  # only 1 game

    feats = fe.build_features(
        db, stat_col="points", player_id=100, game_date=today, opponent_team_id=999
    )
    assert feats is None
