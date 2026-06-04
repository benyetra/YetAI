from unittest.mock import patch, MagicMock

from app.services.etl.wnba import _wnba_stats
from app.services.etl.wnba import update_team_offense_stats as uos


def test_run_upserts_offense_rows():
    mock_db = MagicMock()
    with patch(
        "app.services.etl.wnba.update_team_offense_stats.SessionLocal", lambda: mock_db
    ):
        base = [{"TEAM_ID": 1, "TEAM_NAME": "Liberty", "GP": 5, "PTS": 80}]
        adv = [{"TEAM_ID": 1, "PACE": 95.0}]
        with patch(
            "app.services.etl.wnba.update_team_offense_stats._wnba_stats.fetch_team_dashboard",
            side_effect=[base, adv],
        ):
            with patch(
                "app.services.etl.wnba.update_team_offense_stats.upsert_many"
            ) as um:
                out = uos.run(season="2026")

    assert out["status"] == "ok"
    assert out["teams"] == 1
    um.assert_called_once()


def test_run_skipped_when_stats_nba_unavailable():
    with patch(
        "app.services.etl.wnba.update_team_offense_stats._wnba_stats.fetch_team_dashboard",
        side_effect=_wnba_stats.StatsNbaUnavailable("timeout"),
    ):
        out = uos.run(season="2026")

    assert out["status"] == "skipped"
    assert out["reason"] == "stats_nba_unavailable"
