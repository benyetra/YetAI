from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import update_recent_games as urg


def test_update_recent_games_pulls_yesterday_and_day_before(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.update_recent_games.SessionLocal", lambda: mock_db
    )

    with patch("app.services.etl.wnba.update_recent_games._process_day") as pd_:
        pd_.return_value = 5  # rows
        result = urg.run()

    # Called once for each of 2 days
    assert pd_.call_count == 2
    assert result["status"] == "ok"
    assert result["rows_written"] == 10
