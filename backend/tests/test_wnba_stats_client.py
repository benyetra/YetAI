from unittest.mock import patch, MagicMock

import pytest

from app.services.etl.wnba import _wnba_stats as ws


def test_get_team_dashboard_passes_league_id_10():
    with patch(
        "app.services.etl.wnba._wnba_stats.leaguedashteamstats.LeagueDashTeamStats"
    ) as cls:
        instance = MagicMock()
        instance.get_normalized_dict.return_value = {
            "LeagueDashTeamStats": [
                {"TEAM_ID": 1611661315, "TEAM_NAME": "New York Liberty"}
            ]
        }
        cls.return_value = instance

        rows = ws.fetch_team_dashboard(season="2026")

    cls.assert_called_once()
    kwargs = cls.call_args.kwargs
    assert kwargs.get("league_id_nullable") == "10"
    assert kwargs.get("season") == "2026"
    assert kwargs.get("timeout") == ws.STATS_HTTP_TIMEOUT
    assert rows[0]["TEAM_NAME"] == "New York Liberty"


def test_retry_on_exception_backs_off(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "app.services.etl.wnba._wnba_stats.time.sleep", lambda s: sleeps.append(s)
    )

    with patch(
        "app.services.etl.wnba._wnba_stats.leaguedashteamstats.LeagueDashTeamStats"
    ) as cls:
        ok = MagicMock()
        ok.get_normalized_dict.return_value = {
            "LeagueDashTeamStats": [{"TEAM_ID": 1, "TEAM_NAME": "T"}]
        }
        cls.side_effect = [
            Exception("HTTP 429"),
            Exception("HTTP 429"),
            ok,
        ]

        rows = ws.fetch_team_dashboard(season="2026")

    assert len(rows) == 1
    assert sleeps


def test_fast_profile_raises_stats_nba_unavailable_after_two_attempts(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "app.services.etl.wnba._wnba_stats.time.sleep", lambda s: sleeps.append(s)
    )

    with patch(
        "app.services.etl.wnba._wnba_stats.leaguedashteamstats.LeagueDashTeamStats"
    ) as cls:
        cls.side_effect = Exception("read timed out")

        with pytest.raises(ws.StatsNbaUnavailable):
            ws.fetch_team_dashboard(season="2026", profile="fast")

    assert cls.call_count == 2
    assert len(sleeps) == 1
