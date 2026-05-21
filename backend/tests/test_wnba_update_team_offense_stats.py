from unittest.mock import MagicMock, patch

from app.services.etl.wnba import update_team_offense_stats as uos


def test_run_joins_base_with_advanced(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr("app.services.etl.wnba.update_team_offense_stats.SessionLocal", lambda: mock_db)

    base = [
        {"TEAM_ID": 1, "TEAM_NAME": "T1", "GP": 30, "TOV": 12.0, "PTS": 84.0,
         "AST": 19.0, "OREB": 8.5, "FGM": 30.0, "FG_PCT": 0.45, "FG3_PCT": 0.34},
    ]
    advanced = [{"TEAM_ID": 1, "PACE": 81.5}]

    with patch("app.services.etl.wnba.update_team_offense_stats._wnba_stats.fetch_team_dashboard") as fd:
        fd.side_effect = [base, advanced]
        result = uos.run(season="2026")

    assert result == {"status": "ok", "season": "2026", "teams": 1}
    assert mock_db.merge.call_count == 1
    merged = mock_db.merge.call_args.args[0]
    assert merged.team_id == 1
    assert merged.team_name == "T1"
    assert merged.pace == 81.5
    assert merged.points_per_game == 84.0
