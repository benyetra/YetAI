from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.wnba import update_game_lines as ugl


@pytest.fixture
def fake_odds_payload():
    """Three books, one game. Consensus = simple average."""
    return [
        {
            "id": "evt1",
            "commence_time": "2026-05-21T23:00:00Z",
            "home_team": "New York Liberty",
            "away_team": "Las Vegas Aces",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {
                                    "name": "New York Liberty",
                                    "point": -2.5,
                                    "price": -110,
                                },
                                {"name": "Las Vegas Aces", "point": 2.5, "price": -110},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "point": 162.0, "price": -110},
                                {"name": "Under", "point": 162.0, "price": -110},
                            ],
                        },
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "New York Liberty", "price": -130},
                                {"name": "Las Vegas Aces", "price": 110},
                            ],
                        },
                    ],
                },
                {
                    "key": "fanduel",
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {
                                    "name": "New York Liberty",
                                    "point": -3.0,
                                    "price": -110,
                                },
                                {"name": "Las Vegas Aces", "point": 3.0, "price": -110},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "point": 163.0, "price": -110},
                                {"name": "Under", "point": 163.0, "price": -110},
                            ],
                        },
                    ],
                },
            ],
        }
    ]


def test_consensus_averages_across_books(fake_odds_payload, monkeypatch):
    captured = {}
    mock_db = MagicMock(name="Session")

    def capture_upsert(_db, _model, rows, **kwargs):
        captured.update(rows[0])
        return len(rows)

    monkeypatch.setattr(
        "app.services.etl.wnba.update_game_lines.SessionLocal", lambda: mock_db
    )
    monkeypatch.setenv("ODDS_API_KEY", "test")

    with (
        patch("app.services.etl.wnba.update_game_lines._odds_get") as og,
        patch(
            "app.services.etl.wnba.update_game_lines.upsert_many",
            side_effect=capture_upsert,
        ),
    ):
        og.return_value = fake_odds_payload
        result = ugl.run()

    # Consensus spread = avg(-2.5, -3.0) = -2.75
    assert captured["spread_home"] == pytest.approx(-2.75)
    # Consensus total = avg(162.0, 163.0) = 162.5
    assert captured["total"] == pytest.approx(162.5)
    # Moneyline present only at pinnacle → consensus = single book value
    assert captured["moneyline_home"] == -130
    assert captured["bookmaker"] == "consensus"
    assert result == {"status": "ok", "games": 1}


def test_no_data_returns_no_data(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.update_game_lines.SessionLocal", lambda: mock_db
    )
    monkeypatch.setenv("ODDS_API_KEY", "test")

    with (
        patch("app.services.etl.wnba.update_game_lines._odds_get") as og,
        patch("app.services.etl.wnba.update_game_lines.upsert_many") as um,
    ):
        og.return_value = None
        result = ugl.run()

    assert result == {"status": "no_data", "games": 0}
    um.assert_not_called()
