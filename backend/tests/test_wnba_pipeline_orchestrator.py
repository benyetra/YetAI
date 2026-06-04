"""WNBA orchestrator step lists — hourly must not block on stats.nba.com team dashboards."""

from unittest.mock import patch

from app.tasks import etl_pipeline as ep


def test_hourly_pipeline_excludes_team_stats_refresh_steps():
    with patch.object(ep, "_wnba_in_season", return_value=True):
        captured: list[str] = []

        def fake_run():
            return {"status": "ok"}

        for label, _mod in [
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
        ]:
            captured.append(label)
            setattr(_mod, "run", fake_run)

        out = ep.run_wnba_update_pipeline.run()

    assert out["status"] == "ok"
    assert "update_team_offense_stats" not in out["results"]
    assert "update_team_defense_stats" not in out["results"]
    assert "update_team_roster" not in out["results"]
    assert captured == [
        "update_injury_status",
        "update_recent_games",
        "today_active_players",
        "update_expected_minutes",
        "totals_projector",
        "spread_projector",
        "generate_points",
        "generate_assists",
        "generate_rebounds",
        "store_actuals",
        "totals_accuracy",
        "spreads_accuracy",
        "prop_accuracy",
    ]


def test_daily_team_stats_pipeline_includes_dashboard_steps():
    with patch.object(ep, "_wnba_in_season", return_value=True):

        def fake_run(**kwargs):
            return {"status": "ok", "profile": kwargs.get("profile")}

        ep._wnba_update_off.run = lambda **kw: fake_run(**kw)
        ep._wnba_update_def.run = lambda **kw: fake_run(**kw)
        ep._wnba_update_roster.run = lambda **kw: fake_run(**kw)

        out = ep.run_wnba_team_stats_daily.run()

    assert set(out["results"].keys()) == {
        "update_team_offense_stats",
        "update_team_defense_stats",
        "update_team_roster",
    }
    assert out["results"]["update_team_offense_stats"]["profile"] == "default"
