from unittest.mock import MagicMock, patch

from app.services.etl.wnba import update_team_defense_stats as uds


def test_run_joins_opponent_base_and_advanced_dashboards(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.update_team_defense_stats.SessionLocal", lambda: mock_db
    )

    base = [
        {
            "TEAM_ID": 1,
            "TEAM_NAME": "T1",
            "DREB": 24.0,
            "STL": 6.0,
            "BLK": 3.5,
            "PF": 17.0,
        }
    ]
    defense = [
        {
            "TEAM_ID": 1,
            "TEAM_NAME": "T1",
            "OPP_PTS": 80.0,
            "OPP_AST": 18.0,
            "OPP_REB": 33.0,
            "OPP_OREB": 7.0,
            "OPP_FG_PCT": 0.43,
            "OPP_FG3_PCT": 0.32,
            "OPP_FG3M": 7.5,
            "OPP_FG3A": 23.0,
            "OPP_FTM": 13.0,
            "OPP_TOV": 11.5,
        }
    ]
    advanced = [{"TEAM_ID": 1, "PACE": 80.0, "DEF_RATING": 99.5}]

    with patch(
        "app.services.etl.wnba.update_team_defense_stats._wnba_stats.fetch_team_dashboard"
    ) as fd:
        fd.side_effect = [base, defense, advanced]
        with patch("app.services.etl.wnba.update_team_defense_stats.upsert_many") as um:
            result = uds.run(season="2026")

    assert result == {"status": "ok", "season": "2026", "teams": 1}
    row = um.call_args[0][2][0]
    assert row["team_id"] == 1
    assert row["points_allowed_per_game"] == 80.0
    assert row["defensive_rebounds"] == 24.0
    assert row["steals"] == 6.0
    assert row["defensive_rating"] == 99.5
    assert row["pace"] == 80.0
