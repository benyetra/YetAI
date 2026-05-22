from unittest.mock import MagicMock, patch

from app.services.etl.wnba import update_team_roster as urr


def test_run_prefers_league_player_stats(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr("app.services.etl.wnba.update_team_roster.SessionLocal", lambda: mock_db)

    with patch(
        "app.services.etl.wnba.update_team_roster._wnba_stats.fetch_league_player_stats"
    ) as fps:
        fps.return_value = [
            {
                "TEAM_ID": 1611661319,
                "PLAYER_ID": 1,
                "PLAYER_NAME": "A'ja Wilson",
            },
            {
                "TEAM_ID": 1611661319,
                "PLAYER_ID": 2,
                "PLAYER_NAME": "Kelsey Plum",
            },
        ]
        with patch(
            "app.services.etl.wnba.update_team_roster._wnba_stats.fetch_team_roster"
        ) as fr:
            with patch("app.services.etl.wnba.update_team_roster.upsert_many") as um:
                result = urr.run(season="2026")

    assert result["status"] == "ok"
    assert result["source"] == "league_dash_player_stats"
    assert result["players_seen"] == 2
    fr.assert_not_called()
    um.assert_called_once()
    assert mock_db.commit.called


def test_run_falls_back_to_per_team_when_league_empty(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr("app.services.etl.wnba.update_team_roster.SessionLocal", lambda: mock_db)

    with patch(
        "app.services.etl.wnba.update_team_roster._wnba_stats.fetch_league_player_stats"
    ) as fps:
        fps.return_value = []
        with patch(
            "app.services.etl.wnba.update_team_roster._wnba_stats.fetch_team_roster"
        ) as fr:
            fr.return_value = [
                {"PLAYER_ID": 1, "PLAYER": "A'ja Wilson", "POSITION": "F"},
            ]
            with patch(
                "app.services.etl.wnba.update_team_roster.WNBA_ID_TO_NAME",
                {1611661319: "Las Vegas Aces"},
            ):
                with patch("app.services.etl.wnba.update_team_roster.upsert_many") as um:
                    result = urr.run(season="2026")

    assert result["status"] == "ok"
    assert result["source"] == "common_team_roster"
    assert result["teams_processed"] == 1
    assert result["players_seen"] == 1
    fr.assert_called_once()
    um.assert_called_once()


def test_run_handles_per_team_fetch_failure_gracefully(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr("app.services.etl.wnba.update_team_roster.SessionLocal", lambda: mock_db)

    with patch(
        "app.services.etl.wnba.update_team_roster._wnba_stats.fetch_league_player_stats",
        side_effect=RuntimeError("upstream failure"),
    ):
        with patch(
            "app.services.etl.wnba.update_team_roster._wnba_stats.fetch_team_roster",
            side_effect=RuntimeError("upstream failure"),
        ):
            with patch(
                "app.services.etl.wnba.update_team_roster.WNBA_ID_TO_NAME",
                {1611661319: "Las Vegas Aces"},
            ):
                result = urr.run(season="2026")

    assert result["status"] == "ok"
    assert result["source"] == "common_team_roster"
    assert result["errors"] == 1
    assert result["teams_processed"] == 0
