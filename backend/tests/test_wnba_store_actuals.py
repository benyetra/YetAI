from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import store_actuals as sa


def test_run_writes_totals_and_spread_actuals(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.store_actuals.SessionLocal", lambda: mock_db
    )

    with patch("app.services.etl.wnba.store_actuals.fetch_games") as fg:
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
    # 2 merge calls: one totals + one spread actual
    assert mock_db.merge.call_count == 2

    spread_obj = mock_db.merge.call_args_list[1].args[0]
    assert spread_obj.actual_margin == 7
    assert spread_obj.home_won is True


def test_run_skips_incomplete_games(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.store_actuals.SessionLocal", lambda: mock_db
    )

    with patch("app.services.etl.wnba.store_actuals.fetch_games") as fg:
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
    mock_db.merge.assert_not_called()
