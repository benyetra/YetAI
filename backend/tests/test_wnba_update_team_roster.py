from unittest.mock import MagicMock, patch

from app.services.etl.wnba import update_team_roster as urr


def test_run_upserts_each_player(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr("app.services.etl.wnba.update_team_roster.SessionLocal", lambda: mock_db)

    with patch("app.services.etl.wnba.update_team_roster._wnba_stats.fetch_team_roster") as fr:
        fr.return_value = [
            {"PLAYER_ID": 1, "PLAYER": "A'ja Wilson", "POSITION": "F"},
            {"PLAYER_ID": 2, "PLAYER": "Kelsey Plum", "POSITION": "G"},
        ]
        with patch(
            "app.services.etl.wnba.update_team_roster.WNBA_ID_TO_NAME",
            {1611661319: "Las Vegas Aces"},
        ):
            with patch("app.services.etl.wnba.update_team_roster.upsert_many") as um:
                result = urr.run(season="2026")

    assert result["status"] == "ok"
    assert result["teams_processed"] == 1
    assert result["players_seen"] == 2
    um.assert_called_once()
    rows = um.call_args[0][2]
    assert len(rows) == 2
    assert mock_db.commit.called


def test_run_handles_fetch_failure_gracefully(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr("app.services.etl.wnba.update_team_roster.SessionLocal", lambda: mock_db)

    with patch("app.services.etl.wnba.update_team_roster._wnba_stats.fetch_team_roster") as fr:
        fr.side_effect = RuntimeError("upstream failure")
        with patch(
            "app.services.etl.wnba.update_team_roster.WNBA_ID_TO_NAME",
            {1611661319: "Las Vegas Aces"},
        ):
            result = urr.run(season="2026")

    assert result["status"] == "ok"
    assert result["errors"] == 1
    assert result["teams_processed"] == 0
