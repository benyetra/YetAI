"""Tests for Odds API event + pitcher name matching in MLB strikeouts ETL."""

from app.services.etl.mlb._enrichment_helpers import (
    find_event_for_game,
    pitcher_names_match,
)


def test_pitcher_names_match_accent_and_last_name():
    assert pitcher_names_match("Martin Perez", "Martín Pérez")
    assert pitcher_names_match("Parker Messick", "Parker Messick")
    assert not pitcher_names_match("Bryan Woo", "Dylan Cease")


def test_find_event_for_game_athletics_alias():
    game = {
        "home_name": "San Diego Padres",
        "away_name": "Athletics",
    }
    events = [
        {
            "id": "evt1",
            "home_team": "San Diego Padres",
            "away_team": "Oakland Athletics",
        }
    ]
    event = find_event_for_game(game, events)
    assert event is not None
    assert event["id"] == "evt1"
