from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import update_expected_minutes as uem


def test_expected_minutes_uses_l5_average(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.update_expected_minutes.SessionLocal", lambda: mock_db
    )

    # Active row for player 100
    active = MagicMock()
    active.player_id = 100

    # 5 recent games: avg minutes = 30
    recent = [MagicMock(minutes=30.0) for _ in range(5)]

    mock_db.query.return_value.filter.return_value.all.return_value = [active]
    # second query: WNBARecentGames for player 100, last 5
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
        recent
    )

    result = uem.run()

    assert result["status"] == "ok"
    assert result["players_updated"] >= 1
    # The active row's expected_minutes was set
    assert active.expected_minutes == 30.0


def test_player_with_no_history_gets_default(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.update_expected_minutes.SessionLocal", lambda: mock_db
    )

    active = MagicMock()
    active.player_id = 999
    mock_db.query.return_value.filter.return_value.all.return_value = [active]
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
        []
    )

    uem.run()
    # Default: no history → leave None (do not project)
    assert active.expected_minutes is None
