from unittest.mock import MagicMock, patch

from app.services.etl.wnba import update_injury_status as uis


def _make_session_with_roster(player_id: int, player_name: str):
    mock_db = MagicMock(name="Session")
    roster = MagicMock()
    roster.player_id = player_id
    roster.player_name = player_name
    mock_db.query.return_value.filter.return_value.first.return_value = roster
    return mock_db, roster


def test_run_matches_roster_and_normalizes_status(monkeypatch):
    mock_db, _ = _make_session_with_roster(123, "A'ja Wilson")
    monkeypatch.setattr("app.services.etl.wnba.update_injury_status.SessionLocal", lambda: mock_db)

    with patch("app.services.etl.wnba.update_injury_status.fetch_injuries") as fi:
        fi.return_value = [
            {"player_name": "A'ja Wilson", "team_name": "Las Vegas Aces",
             "status": "Day-To-Day", "injury_type": "ankle"},
        ]
        with patch("app.services.etl.wnba.update_injury_status.upsert_many") as um:
            result = uis.run()

    assert result["matched"] == 1
    assert result["unmatched"] == 0
    row = um.call_args[0][2][0]
    assert row["player_id"] == 123
    assert row["status"] == "questionable"  # Day-To-Day → questionable
    assert row["injury_type"] == "ankle"


def test_run_skips_unmatched_player(monkeypatch):
    mock_db = MagicMock(name="Session")
    mock_db.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr("app.services.etl.wnba.update_injury_status.SessionLocal", lambda: mock_db)

    with patch("app.services.etl.wnba.update_injury_status.fetch_injuries") as fi:
        fi.return_value = [
            {"player_name": "Unknown Player", "team_name": "X", "status": "Out", "injury_type": None},
        ]
        result = uis.run()

    assert result["matched"] == 0
    assert result["unmatched"] == 1
    mock_db.execute.assert_not_called()


def test_unknown_status_defaults_to_out(monkeypatch):
    mock_db, _ = _make_session_with_roster(1, "P")
    monkeypatch.setattr("app.services.etl.wnba.update_injury_status.SessionLocal", lambda: mock_db)

    with patch("app.services.etl.wnba.update_injury_status.fetch_injuries") as fi:
        fi.return_value = [{"player_name": "P", "team_name": "X", "status": "Mystery", "injury_type": None}]
        with patch("app.services.etl.wnba.update_injury_status.upsert_many") as um:
            uis.run()

    assert um.call_args[0][2][0]["status"] == "out"
