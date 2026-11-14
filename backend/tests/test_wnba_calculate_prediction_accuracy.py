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
        three_pt_made=3,
    )
    mock_db.query.return_value.filter.return_value.all.return_value = [recent_row]

    with patch("app.services.etl.wnba.calculate_prediction_accuracy.upsert_many") as um:
        result = cpa.run()

    assert result["status"] == "ok"
    assert um.call_count == 5
    assert len(um.call_args_list[0][0][2]) == 1


def test_run_grades_each_lookback_day_with_its_own_date(monkeypatch):
    """H-8: rows from earlier days in the window are filed under their own date."""
    monkeypatch.setattr(
        "app.services.etl.wnba.calculate_prediction_accuracy.now_eastern",
        lambda: __import__("datetime").datetime(2026, 6, 15, 8, 0),
    )
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.calculate_prediction_accuracy.SessionLocal",
        lambda: mock_db,
    )
    old = MagicMock(
        player_id=1,
        game_date=date(2026, 6, 12),
        points=10,
        assists=1,
        rebounds=1,
        three_pt_made=1,
    )
    new = MagicMock(
        player_id=1,
        game_date=date(2026, 6, 14),
        points=20,
        assists=2,
        rebounds=2,
        three_pt_made=2,
    )
    mock_db.query.return_value.filter.return_value.all.return_value = [old, new]

    with patch("app.services.etl.wnba.calculate_prediction_accuracy.upsert_many") as um:
        result = cpa.run()

    points = um.call_args_list[0][0][2]
    assert [(r["date"], r["actual_points"]) for r in points] == [
        (date(2026, 6, 12), 10.0),
        (date(2026, 6, 14), 20.0),
    ]
    assert result["dates"] == ["2026-06-12", "2026-06-13", "2026-06-14"]
