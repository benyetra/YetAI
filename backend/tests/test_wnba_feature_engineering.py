from datetime import date, timedelta
from unittest.mock import MagicMock

from app.services.etl.wnba import _feature_engineering as fe


def _mk_recent_game(d, **stats):
    g = MagicMock()
    g.game_date = d
    g.opponent_team_id = stats.get("opponent_team_id", 999)
    g.home_game = stats.get("home_game", True)
    for k, v in stats.items():
        if k in ("opponent_team_id", "home_game"):
            continue
        setattr(g, k, v)
    for k in (
        "minutes",
        "points",
        "assists",
        "rebounds",
        "fg_attempts",
        "field_goals_made",
        "three_pt_made",
        "ft_attempts",
        "usage_percentage",
        "true_shooting_percentage",
        "effective_field_goal_percentage",
        "offensive_rating",
        "defensive_rating",
        "assist_percentage",
        "plus_minus",
        "pace",
    ):
        if not hasattr(g, k) or getattr(g, k) is None:
            if k not in stats:
                setattr(g, k, 0.0)
    return g


def _stub_db(games, *, opponent_team_id=999):
    db = MagicMock()

    def query_side(model):
        q = MagicMock()
        if model.__name__ == "WNBARecentGames":
            q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
                games
            )
        elif model.__name__ == "WNBATeamDefenseStats":
            q.filter.return_value.first.return_value = MagicMock(
                points_allowed_per_game=80.0,
                assists_allowed_per_game=18.0,
                rebounds_allowed_per_game=33.0,
                defensive_rating=100.0,
            )
        elif model.__name__ == "WNBATeamOffenseStats":
            q.filter.return_value.first.return_value = MagicMock(
                pace=80.0,
                team_name="Test Team",
            )
        elif model.__name__ == "WNBATeamRoster":
            q.filter_by.return_value.first.return_value = MagicMock(team_id=1)
        elif model.__name__ == "WNBAGameLines":
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query_side
    return db


def test_l3_l5_l10_averages_computed():
    today = date(2026, 6, 15)
    games = [
        _mk_recent_game(
            today - timedelta(days=i + 1),
            points=10 + i,
            assists=2 + i,
            rebounds=5 + i,
            minutes=36.0 if i == 0 else 28.0,
            field_goals_made=8,
            three_pt_made=2,
            fg_attempts=16,
            ft_attempts=4,
            opponent_team_id=999 if i > 2 else 888,
        )
        for i in range(10)
    ]
    db = _stub_db(games)

    feats = fe.build_features(
        db, stat_col="points", player_id=100, game_date=today, opponent_team_id=999
    )

    assert feats is not None
    assert feats["points_l3"] == 11.0
    assert feats["points_l5"] == 12.0
    assert feats["points_l10"] == 14.5
    assert feats["opp_points_allowed_per_game"] == 80.0
    assert feats["opp_defensive_rating"] == 100.0
    assert feats["points_std_l5"] > 0
    assert feats["points_trend_pct"] != 0
    assert feats["points_matchup_games"] == 7.0
    assert feats["expected_minutes"] > feats["minutes_l5"]
    assert feats["minutes_delta_l5"] > 0
    assert feats["is_starter"] == 1.0
    assert feats["efg_l5"] > 0
    assert feats["season_efg_pct"] > 0
    assert feats["effective_field_goal_percentage_avg"] > 0
    assert "usage_percentage_avg" in feats


def test_insufficient_history_returns_none():
    today = date(2026, 6, 15)
    db = _stub_db([_mk_recent_game(today - timedelta(days=1), points=10, minutes=30)])

    feats = fe.build_features(
        db, stat_col="points", player_id=100, game_date=today, opponent_team_id=999
    )
    assert feats is None


def test_apply_expected_minutes_overlays_delta():
    base = {"minutes_l5": 28.0, "expected_minutes": 28.0, "minutes_delta_l5": 0.0}
    out = fe.apply_expected_minutes(base, 32.0)
    assert out["expected_minutes"] == 32.0
    assert out["minutes_delta_l5"] == 4.0
