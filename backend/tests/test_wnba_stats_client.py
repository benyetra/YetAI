from unittest.mock import patch, MagicMock

from app.services.etl.wnba import _wnba_stats as ws


def test_get_team_dashboard_passes_league_id_10():
    with patch("app.services.etl.wnba._wnba_stats.leaguedashteamstats.LeagueDashTeamStats") as cls:
        instance = MagicMock()
        instance.get_normalized_dict.return_value = {
            "LeagueDashTeamStats": [{"TEAM_ID": 1611661315, "TEAM_NAME": "New York Liberty"}]
        }
        cls.return_value = instance

        rows = ws.fetch_team_dashboard(season="2026")

    cls.assert_called_once()
    kwargs = cls.call_args.kwargs
    # nba_api uses `league_id_nullable` for LeagueDashTeamStats — pinned to "10" for WNBA
    assert kwargs.get("league_id_nullable") == "10"
    assert kwargs.get("season") == "2026"
    assert rows[0]["TEAM_NAME"] == "New York Liberty"


def test_retry_on_exception_backs_off(monkeypatch):
    sleeps = []
    monkeypatch.setattr("app.services.etl.wnba._wnba_stats.time.sleep", lambda s: sleeps.append(s))

    with patch("app.services.etl.wnba._wnba_stats.leaguedashteamstats.LeagueDashTeamStats") as cls:
        ok = MagicMock()
        ok.get_normalized_dict.return_value = {"LeagueDashTeamStats": [{"TEAM_ID": 1, "TEAM_NAME": "T"}]}
        cls.side_effect = [
            Exception("HTTP 429"),
            Exception("HTTP 429"),
            ok,
        ]

        rows = ws.fetch_team_dashboard(season="2026")

    assert len(rows) == 1
    assert sleeps  # at least one backoff sleep happened
