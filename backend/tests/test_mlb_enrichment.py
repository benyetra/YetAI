"""Unit tests for MLB enrichment helpers (no statsapi import chain)."""

from app.services.etl.mlb._enrichment_helpers import (
    flatten_batters,
    game_odds_key,
    match_team_price,
)


def test_flatten_batters_already_flat():
    batters = [
        {"player_id": "1", "team": "Yankees", "combined_score": 4.0},
        {"player_id": "2", "team": "Red Sox", "combined_score": 3.5},
    ]
    assert flatten_batters(batters) == batters


def test_flatten_batters_nested_lists():
    inner = [{"player_id": "1", "team": "Yankees"}]
    assert flatten_batters([inner]) == inner


def test_match_team_price_fuzzy():
    prices = {
        "Boston Red Sox": -110,
        "New York Yankees": 105,
    }
    price, label = match_team_price("Boston Red Sox", prices)
    assert price == -110
    assert label == "Boston Red Sox"


def test_game_odds_key_matches_odds_map_format():
    game = {
        "away_name": "Boston Red Sox",
        "home_name": "New York Yankees",
        "game_id": 777,
    }
    assert game_odds_key(game) == "Boston Red Sox @ New York Yankees"
    assert "(#" not in game_odds_key(game)
