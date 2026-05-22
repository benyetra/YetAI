from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.wnba import spread_projector as sp


def test_initial_elo_is_1500():
    assert sp.INITIAL_ELO == 1500.0


def test_elo_update_winner_gains_loser_loses_zero_sum():
    home_elo, away_elo = 1600, 1500
    new_home, new_away = sp.update_elo(home_elo, away_elo, home_score=92, away_score=85)
    assert new_home > home_elo
    assert new_away < away_elo
    assert abs((new_home - home_elo) + (new_away - away_elo)) < 1e-6


def test_expected_margin_at_equal_rating_is_hca():
    margin = sp.expected_margin(home_elo=1500, away_elo=1500)
    assert margin == pytest.approx(sp.HOME_COURT_ADVANTAGE)


def test_win_prob_monotonic_in_margin():
    assert sp.margin_to_win_prob(10.0) > sp.margin_to_win_prob(2.0)
    assert sp.margin_to_win_prob(0.0) == pytest.approx(0.5, abs=0.001)
    assert sp.margin_to_win_prob(-5.0) < 0.5


def test_pace_overlay_returns_zero_when_any_input_missing():
    assert sp.pace_overlay_adjustment(None, 100, 100, 100) == 0.0
    assert sp.pace_overlay_adjustment(100, 100, 100, None) == 0.0


def test_run_writes_projection_for_each_market_line(monkeypatch):
    mock_db = MagicMock(name="Session")
    game = MagicMock()
    game.game_date = date(2026, 5, 21)
    game.home_team_id = 1611661315
    game.away_team_id = 1611661319
    game.home_team_name = "New York Liberty"
    game.away_team_name = "Las Vegas Aces"
    game.spread_home = -2.5
    game.total = 162.5

    # query(WNBASpreadActuals).order_by(...).all() → []
    # query(WNBATeamOffenseStats).all() → []
    # query(WNBATeamDefenseStats).all() → []
    # query(WNBAGameLines).filter(...).all() → [game]
    mock_db.query.return_value.order_by.return_value.all.return_value = []
    mock_db.query.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.all.return_value = [game]

    monkeypatch.setattr(
        "app.services.etl.wnba.spread_projector.SessionLocal", lambda: mock_db
    )
    monkeypatch.setattr(
        "app.services.etl.wnba.spread_projector._load_elos",
        lambda db: {
            "New York Liberty": 1550.0,
            "Las Vegas Aces": 1580.0,
        },
    )

    with patch("app.services.etl.wnba.spread_projector.upsert_many") as um:
        result = sp.run()

    assert result["status"] == "ok"
    assert result["games"] == 1
    row = um.call_args[0][2][0]
    assert row["home_elo"] == 1550.0
    assert row["away_elo"] == 1580.0
    assert row["market_spread_home"] == -2.5
    assert row["recommendation"] in {"HOME", "AWAY", "NO_PLAY"}
