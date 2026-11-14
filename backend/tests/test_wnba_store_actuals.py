from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import store_actuals as sa


def test_run_writes_totals_and_spread_actuals(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.store_actuals.SessionLocal", lambda: mock_db
    )

    with (
        patch("app.services.etl.wnba.store_actuals.fetch_games") as fg,
        patch("app.services.etl.wnba.store_actuals.upsert_many") as um,
    ):
        fg.return_value = [
            {
                "completed": True,
                "home_team_name": "New York Liberty",
                "away_team_name": "Las Vegas Aces",
                "home_score": 92,
                "away_score": 85,
            }
        ]
        result = sa.run(target_date=date(2026, 5, 21))

    assert result["totals_written"] == 1
    assert result["spreads_written"] == 1
    assert um.call_count == 2

    spread_rows = um.call_args_list[1][0][2]
    assert spread_rows[0]["actual_margin"] == 7
    assert spread_rows[0]["home_won"] is True


def test_run_skips_incomplete_games(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.store_actuals.SessionLocal", lambda: mock_db
    )

    with (
        patch("app.services.etl.wnba.store_actuals.fetch_games") as fg,
        patch("app.services.etl.wnba.store_actuals.upsert_many") as um,
    ):
        fg.return_value = [
            {
                "completed": False,
                "home_team_name": "X",
                "away_team_name": "Y",
                "home_score": None,
                "away_score": None,
            }
        ]
        result = sa.run(target_date=date(2026, 5, 21))

    assert result["totals_written"] == 0
    assert result["spreads_written"] == 0
    um.assert_not_called()


def test_default_run_grades_the_lookback_window(monkeypatch):
    """H-8: no target_date grades every grading_dates day with one upsert pass."""
    from datetime import datetime

    monkeypatch.setattr(
        "app.services.etl.wnba.store_actuals.SessionLocal", lambda: MagicMock()
    )
    monkeypatch.setattr(
        "app.services.etl.wnba.store_actuals.now_eastern",
        lambda: datetime(2026, 6, 15, 8, 0),
    )
    monkeypatch.setenv("WNBA_GRADING_LOOKBACK_DAYS", "3")
    game = {
        "completed": True,
        "home_team_name": "New York Liberty",
        "away_team_name": "Las Vegas Aces",
        "home_score": 90,
        "away_score": 80,
    }
    with (
        patch("app.services.etl.wnba.store_actuals.fetch_games") as fg,
        patch("app.services.etl.wnba.store_actuals.upsert_many") as um,
    ):
        fg.return_value = [game]
        result = sa.run()

    assert [c.args[0] for c in fg.call_args_list] == [
        date(2026, 6, 12),
        date(2026, 6, 13),
        date(2026, 6, 14),
    ]
    assert result["totals_written"] == 3
    assert {r["game_date"] for r in um.call_args_list[0][0][2]} == {
        date(2026, 6, 12),
        date(2026, 6, 13),
        date(2026, 6, 14),
    }
