"""Smoke tests for WNBA Celery task registration and season gating."""

from datetime import date
from unittest.mock import patch

import pytest


def test_wnba_celery_tasks_registered():
    # Force registration of @celery_app.task decorators in the etl_pipeline module
    import app.tasks.etl_pipeline  # noqa: F401
    from app.celery_app import celery_app

    expected = [
        "app.tasks.etl_pipeline.wnba.update_team_roster",
        "app.tasks.etl_pipeline.wnba.update_team_offense_stats",
        "app.tasks.etl_pipeline.wnba.update_team_defense_stats",
        "app.tasks.etl_pipeline.wnba.update_injury_status",
        "app.tasks.etl_pipeline.wnba.update_game_lines",
        "app.tasks.etl_pipeline.wnba.totals_projector",
        "app.tasks.etl_pipeline.wnba.spread_projector",
        "app.tasks.etl_pipeline.wnba.store_actuals",
        "app.tasks.etl_pipeline.wnba.totals_accuracy",
        "app.tasks.etl_pipeline.wnba.spreads_accuracy",
        "app.tasks.etl_pipeline.run_wnba_update_pipeline",
        "app.tasks.etl_pipeline.wnba.update_recent_games",
        "app.tasks.etl_pipeline.wnba.today_active_players",
        "app.tasks.etl_pipeline.wnba.update_expected_minutes",
        "app.tasks.etl_pipeline.wnba.generate_points",
        "app.tasks.etl_pipeline.wnba.generate_assists",
        "app.tasks.etl_pipeline.wnba.generate_rebounds",
        "app.tasks.etl_pipeline.wnba.prop_accuracy",
    ]
    for name in expected:
        assert name in celery_app.tasks, f"missing task {name}"


def test_wnba_beat_entries_registered():
    from app.celery_app import celery_app

    entries = celery_app.conf.beat_schedule
    expected = [
        "wnba-update-pipeline-daily",
        "wnba-update-game-lines-thrice-daily",
        "wnba-update-injuries-every-2h",
        "wnba-projectors-pregame-hourly",
        "wnba-store-actuals-morning",
        "wnba-totals-accuracy-morning",
        "wnba-spreads-accuracy-morning",
    ]
    for name in expected:
        assert name in entries, f"missing beat entry {name}"


def test_in_season_gate_returns_true_during_may():
    from app.tasks.etl_pipeline import _wnba_in_season

    with patch("app.tasks.etl_pipeline._date") as d:
        d.today.return_value = date(2026, 5, 15)
        # Re-export `date` so date(year, m, d) constructor works
        d.side_effect = date
        assert _wnba_in_season() is True


def test_out_of_season_gate_returns_false_in_february():
    from app.tasks.etl_pipeline import _wnba_in_season

    with patch("app.tasks.etl_pipeline._date") as d:
        d.today.return_value = date(2026, 2, 15)
        d.side_effect = date
        assert _wnba_in_season() is False
