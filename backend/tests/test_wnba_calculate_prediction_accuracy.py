from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import calculate_prediction_accuracy as cpa


def test_run_writes_actuals_for_each_prop_from_recent_games(monkeypatch):
    yesterday = date(2026, 6, 14)
    monkeypatch.setattr(
        "app.services.etl.wnba.calculate_prediction_accuracy.now_eastern",
        lambda: __import__("datetime").datetime(2026, 6, 15, 8, 0),
    )

    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.calculate_prediction_accuracy.SessionLocal",
        lambda: mock_db,
    )

    recent_row = MagicMock(
        player_id=100,
        game_date=yesterday,
        points=20,
        assists=5,
        rebounds=8,
    )
    mock_db.query.return_value.filter.return_value.all.return_value = [recent_row]

    with patch("app.services.etl.wnba.calculate_prediction_accuracy.upsert_many") as um:
        result = cpa.run()

    assert result["status"] == "ok"
    assert um.call_count == 3
    assert len(um.call_args_list[0][0][2]) == 1
