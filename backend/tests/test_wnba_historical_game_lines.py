from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.wnba import update_game_lines as ugl
from app.services.etl.wnba._game_lines_odds import (
    game_line_row_from_event,
    game_line_rows_from_events,
)
from app.services.etl.wnba.historical_game_lines import (
    CREDITS_PER_DATE,
    backfill_dates,
    fetch_historical_events,
)


@pytest.fixture
def fake_odds_payload():
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


def test_game_line_rows_from_events_consensus(fake_odds_payload):
    row = game_line_rows_from_events(fake_odds_payload)[0]
    assert row["spread_home"] == pytest.approx(-2.75)
    assert row["total"] == pytest.approx(162.5)
    assert row["moneyline_home"] == -130
    assert row["bookmaker"] == "consensus"
    assert row["home_team_name"] == "New York Liberty"


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

    assert captured["spread_home"] == pytest.approx(-2.75)
    assert captured["total"] == pytest.approx(162.5)
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


def test_fetch_historical_events_parses_data_wrapper(monkeypatch, fake_odds_payload):
    class FakeResp:
        status_code = 200
        text = ""
        headers = {"x-requests-last": "30", "x-requests-remaining": "470"}

        def json(self):
            return {"data": fake_odds_payload}

    monkeypatch.setenv("ODDS_API_KEY", "test-key")
    with patch(
        "app.services.odds_api_sync.sync_odds_get",
        return_value=FakeResp(),
    ):
        events = fetch_historical_events(date(2024, 6, 1))
    assert events == fake_odds_payload


def test_backfill_dates_dry_run():
    result = backfill_dates(
        [date(2024, 6, 1), date(2024, 6, 2)],
        dry_run=True,
        skip_existing=False,
    )
    assert result["status"] == "dry_run"
    assert result["dates_to_fetch"] == 2
    assert result["estimated_credits"] == 2 * CREDITS_PER_DATE


def test_game_line_row_skips_missing_teams():
    assert game_line_row_from_event({"home_team": "", "away_team": "X"}) is None
