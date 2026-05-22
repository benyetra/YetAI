"""Tests for ESPN WNBA scoreboard parser."""

from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from app.services.etl.wnba import _espn


@pytest.fixture
def fake_scoreboard_payload():
    return {
        "events": [
            {
                "id": "401736000",
                "date": "2026-05-21T23:00Z",
                "competitions": [
                    {
                        "competitors": [
                            {
                                "id": "20",
                                "homeAway": "home",
                                "team": {"displayName": "New York Liberty", "id": "20"},
                                "score": "92",
                            },
                            {
                                "id": "9",
                                "homeAway": "away",
                                "team": {"displayName": "Las Vegas Aces", "id": "9"},
                                "score": "88",
                            },
                        ],
                        "status": {"type": {"completed": True}},
                    }
                ],
            }
        ]
    }


def test_fetch_games_returns_normalized_rows(fake_scoreboard_payload):
    with patch("app.services.etl.wnba._espn.requests.get") as get:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = fake_scoreboard_payload
        get.return_value = resp

        rows = _espn.fetch_games(date(2026, 5, 21))

    assert len(rows) == 1
    g = rows[0]
    assert g["home_team_name"] == "New York Liberty"
    assert g["away_team_name"] == "Las Vegas Aces"
    assert g["home_score"] == 92
    assert g["away_score"] == 88
    assert g["completed"] is True


def test_fetch_games_handles_empty_slate():
    with patch("app.services.etl.wnba._espn.requests.get") as get:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"events": []}
        get.return_value = resp

        rows = _espn.fetch_games(date(2026, 5, 21))

    assert rows == []


def test_now_eastern_is_in_new_york():
    n = _espn.now_eastern()
    assert n.tzinfo is not None
    assert "New_York" in str(n.tzinfo)
