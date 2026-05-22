from unittest.mock import MagicMock, patch

from app.services.etl.wnba import today_active_players as tap


def _mk_roster_row(player_id: int, player_name: str, team_id: int) -> MagicMock:
    row = MagicMock()
    row.player_id = player_id
    row.player_name = player_name
    row.team_id = team_id
    return row


def test_run_writes_one_row_per_active_player(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.today_active_players.SessionLocal",
        lambda: mock_db,
    )

    games_payload = [
        {
            "espn_event_id": "1",
            "home_team_id_espn": "20",  # Atlanta -> 1611661330
            "away_team_id_espn": "17",  # Las Vegas -> 1611661319
            "home_team_name": "Atlanta Dream",
            "away_team_name": "Las Vegas Aces",
            "home_score": None,
            "away_score": None,
            "completed": False,
            "game_time_utc": None,
        }
    ]

    roster_rows = [
        _mk_roster_row(100, "P1", 1611661330),
        _mk_roster_row(101, "P2", 1611661330),
        _mk_roster_row(200, "P3", 1611661319),
    ]
    mock_db.query.return_value.filter.return_value.all.return_value = roster_rows

    with patch("app.services.etl.wnba.today_active_players.fetch_games") as fg:
        fg.return_value = games_payload
        with patch("app.services.etl.wnba.today_active_players.upsert_many") as um:
            result = tap.run()

    assert result["status"] == "ok"
    assert result["games"] == 1
    assert result["players"] == 3
    assert result["kept_stale"] is False
    um.assert_called_once()
    assert len(um.call_args[0][2]) == 3
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()


def test_no_games_keeps_stale_data(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.today_active_players.SessionLocal",
        lambda: mock_db,
    )
    with patch("app.services.etl.wnba.today_active_players.fetch_games") as fg:
        fg.return_value = []
        result = tap.run()

    assert result["games"] == 0
    assert result.get("kept_stale") is True
    mock_db.execute.assert_not_called()
