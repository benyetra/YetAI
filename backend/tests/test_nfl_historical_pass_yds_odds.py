"""Tests for historical NFL pass-yards odds helpers."""

from __future__ import annotations

from app.services.etl.nfl.historical_pass_yds_odds import (
    extract_pass_yds_lines,
    lookup_pass_yds_line,
    match_event,
    normalize_player_key,
)


def test_normalize_player_key_initial_last():
    assert normalize_player_key("Josh Allen") == "j|allen"
    assert normalize_player_key("J. Allen") == "j|allen"
    assert normalize_player_key("J.Allen") == "j|allen"


def test_lookup_pass_yds_line_matches_full_team_name():
    index = {
        "by_key": {
            "2025|3|j|allen|evt1": {
                "season": 2025,
                "week": 3,
                "player_name": "Josh Allen",
                "player_key": "j|allen",
                "team_abbr": "BUF",
                "home_abbr": "BUF",
                "away_abbr": "MIA",
                "event_id": "evt1",
                "line": 268.5,
            }
        }
    }
    assert (
        lookup_pass_yds_line(
            season=2025,
            week=3,
            player_name="Josh Allen",
            team_abbr="Buffalo Bills",
            index=index,
        )
        == 268.5
    )
    assert (
        lookup_pass_yds_line(
            season=2025,
            week=3,
            player_name="Josh Allen",
            team_abbr="BUF",
            index=index,
        )
        == 268.5
    )


def test_extract_pass_yds_prefers_draftkings():
    event = {
        "bookmakers": [
            {
                "key": "fanduel",
                "markets": [
                    {
                        "key": "player_pass_yds",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": "Josh Allen",
                                "point": 265.5,
                                "price": -110,
                            },
                            {
                                "name": "Under",
                                "description": "Josh Allen",
                                "point": 265.5,
                                "price": -110,
                            },
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_pass_yds",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": "Josh Allen",
                                "point": 267.5,
                                "price": -115,
                            },
                            {
                                "name": "Under",
                                "description": "Josh Allen",
                                "point": 267.5,
                                "price": -105,
                            },
                        ],
                    }
                ],
            },
        ]
    }
    lines = extract_pass_yds_lines(event)
    assert lines["Josh Allen"]["line"] == 267.5
    assert lines["Josh Allen"]["book"] == "draftkings"
    assert lines["Josh Allen"]["n_books"] == 2


def test_match_event_by_canonical_names():
    from datetime import date

    game = {
        "home_name": "Kansas City Chiefs",
        "away_name": "Buffalo Bills",
        "gameday": date(2024, 10, 6),
    }
    events = [
        {
            "id": "wrong-week",
            "home_team": "Kansas City Chiefs",
            "away_team": "Buffalo Bills",
            "commence_time": "2024-09-01T17:00:00Z",
        },
        {
            "id": "abc",
            "home_team": "Kansas City Chiefs",
            "away_team": "Buffalo Bills",
            "commence_time": "2024-10-06T17:00:00Z",
        },
    ]
    assert match_event(game, events)["id"] == "abc"
