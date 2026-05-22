from datetime import date, timedelta
from unittest.mock import MagicMock

from app.services.etl.wnba import calculate_prediction_accuracy as cpa


def test_run_writes_actuals_for_each_prop_from_recent_games(monkeypatch):
    yesterday = date(2026, 6, 14)
    monkeypatch.setattr("app.services.etl.wnba.calculate_prediction_accuracy.now_eastern",
                        lambda: __import__("datetime").datetime(2026, 6, 15, 8, 0))

    mock_db = MagicMock(name="Session")
    monkeypatch.setattr("app.services.etl.wnba.calculate_prediction_accuracy.SessionLocal", lambda: mock_db)

    # One player game from yesterday: P1 with points=20, ast=5, reb=8
    recent_row = MagicMock(
        player_id=100, game_date=yesterday,
        points=20, assists=5, rebounds=8,
    )
    mock_db.query.return_value.filter.return_value.all.return_value = [recent_row]

    result = cpa.run()
    assert result["status"] == "ok"
    # 3 props × 1 player game = 3 merges
    assert mock_db.merge.call_count == 3
