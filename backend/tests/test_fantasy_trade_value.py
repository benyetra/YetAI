"""Tests for deterministic fantasy trade values."""

from app.services.fantasy_trade_value import (
    calculate_deterministic_trade_value,
    select_trade_partner,
    stable_unit,
)


def test_stable_unit_is_deterministic():
    assert stable_unit("player-42") == stable_unit("player-42")
    assert 0.0 <= stable_unit("any-seed") < 1.0


def test_trade_value_is_deterministic_for_same_player():
    player = {"id": "1234", "position": "WR", "age": 26, "team": "KC"}
    first = calculate_deterministic_trade_value(player, scoring_type="ppr")
    second = calculate_deterministic_trade_value(player, scoring_type="ppr")
    assert first == second
    assert 8.0 <= first <= 45.0


def test_trade_value_differs_by_scoring_type():
    player = {"id": "1234", "position": "WR", "age": 26, "team": "KC"}
    ppr = calculate_deterministic_trade_value(player, scoring_type="ppr")
    standard = calculate_deterministic_trade_value(player, scoring_type="standard")
    assert ppr != standard


def test_select_trade_partner_is_stable():
    teams = [
        {"team_id": 2, "name": "Beta"},
        {"team_id": 1, "name": "Alpha"},
        {"team_id": 3, "name": "Gamma"},
    ]
    first = select_trade_partner(teams, seed="team-7:QB")
    second = select_trade_partner(teams, seed="team-7:QB")
    assert first == second
    assert first is not None
    assert first["team_id"] in {1, 2, 3}
