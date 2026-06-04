"""WNBA orchestrator step lists — hourly must not block on stats.nba.com team dashboards."""

from contextlib import ExitStack
from unittest.mock import patch

from app.tasks import etl_pipeline as ep

_HOURLY_STEPS = [
    ("update_injury_status", ep._wnba_update_injury),
    ("update_recent_games", ep._wnba_update_recent),
    ("today_active_players", ep._wnba_today_active),
    ("update_expected_minutes", ep._wnba_expected_minutes),
    ("totals_projector", ep._wnba_totals_projector),
    ("spread_projector", ep._wnba_spread_projector),
    ("generate_points", ep._wnba_gen_points),
    ("generate_assists", ep._wnba_gen_assists),
    ("generate_rebounds", ep._wnba_gen_rebounds),
    ("store_actuals", ep._wnba_store_actuals),
    ("totals_accuracy", ep._wnba_totals_accuracy),
    ("spreads_accuracy", ep._wnba_spreads_accuracy),
    ("prop_accuracy", ep._wnba_prop_accuracy),
]

_DAILY_TEAM_STATS_STEPS = [
    ("update_team_offense_stats", ep._wnba_update_off),
    ("update_team_defense_stats", ep._wnba_update_def),
    ("update_team_roster", ep._wnba_update_roster),
]


def _fake_run(*_args, **_kwargs):
    return {"status": "ok"}


def test_hourly_pipeline_excludes_team_stats_refresh_steps():
    with patch.object(ep, "_wnba_in_season", return_value=True):
        with ExitStack() as stack:
            for _label, mod in _HOURLY_STEPS:
                stack.enter_context(patch.object(mod, "run", side_effect=_fake_run))
            out = ep.run_wnba_update_pipeline.run()

    assert out["status"] == "ok"
    assert "update_team_offense_stats" not in out["results"]
    assert "update_team_defense_stats" not in out["results"]
    assert "update_team_roster" not in out["results"]
    assert list(out["results"].keys()) == [label for label, _ in _HOURLY_STEPS]


def test_daily_team_stats_pipeline_includes_dashboard_steps():
    def fake_run_with_profile(*_args, profile=None, **_kwargs):
        return {"status": "ok", "profile": profile}

    with patch.object(ep, "_wnba_in_season", return_value=True):
        with ExitStack() as stack:
            for _label, mod in _DAILY_TEAM_STATS_STEPS:
                stack.enter_context(
                    patch.object(mod, "run", side_effect=fake_run_with_profile)
                )
            out = ep.run_wnba_team_stats_daily.run()

    assert set(out["results"].keys()) == {label for label, _ in _DAILY_TEAM_STATS_STEPS}
    assert out["results"]["update_team_offense_stats"]["profile"] == "default"
