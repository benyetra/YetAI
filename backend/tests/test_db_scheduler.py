"""Tests for the DatabaseScheduler overlay logic.

The pure `apply_overrides` function is the core; the actual Celery
Scheduler subclass is just plumbing that calls it on sync.
"""

from __future__ import annotations

from celery.schedules import crontab

from app.core.db_scheduler import apply_overrides
from app.models.database_models import PipelineSchedule


NBA_TASK = "app.tasks.etl_pipeline.run_nba_update_pipeline"
MLB_TASK = "app.tasks.etl_pipeline.run_mlb_update_pipeline"


def test_apply_overrides_replaces_hour_minute_for_known_orchestrator():
    """Override row updates the crontab for a known orchestrator."""
    schedule_dict = {
        "nba-daily": {
            "task": NBA_TASK,
            "schedule": crontab(hour=3, minute=30),
        },
    }
    override = PipelineSchedule(
        beat_key="nba-daily",
        task_name=NBA_TASK,
        hour=6,
        minute=15,
        enabled=True,
    )
    out = apply_overrides(schedule_dict, {"nba-daily": override})

    new_cron = out["nba-daily"]["schedule"]
    assert new_cron.hour == {6}
    assert new_cron.minute == {15}
    assert schedule_dict["nba-daily"]["schedule"].hour == {3}


def test_apply_overrides_removes_entry_when_disabled():
    schedule_dict = {
        "nba-daily": {"task": NBA_TASK, "schedule": crontab(hour=3, minute=30)}
    }
    override = PipelineSchedule(
        beat_key="nba-daily",
        task_name=NBA_TASK,
        hour=6,
        minute=15,
        enabled=False,
    )
    out = apply_overrides(schedule_dict, {"nba-daily": override})
    assert "nba-daily" not in out


def test_apply_overrides_ignores_orphan_overrides():
    schedule_dict = {
        "nba-daily": {"task": NBA_TASK, "schedule": crontab(hour=3, minute=30)}
    }
    orphan = PipelineSchedule(
        beat_key="orphan-beat-key",
        task_name="some.removed.task",
        hour=6,
        minute=15,
        enabled=True,
    )
    out = apply_overrides(schedule_dict, {"orphan-beat-key": orphan})
    assert out == schedule_dict


def test_apply_overrides_skips_non_orchestrator_tasks():
    schedule_dict = {
        "games-cache": {
            "task": "app.tasks.games_sync.sync_games_cache",
            "schedule": crontab(hour=6, minute=0),
        },
    }
    override = PipelineSchedule(
        beat_key="games-cache",
        task_name="app.tasks.games_sync.sync_games_cache",
        hour=6,
        minute=15,
        enabled=True,
    )
    out = apply_overrides(schedule_dict, {"games-cache": override})
    assert out["games-cache"]["schedule"] == crontab(hour=6, minute=0)


def test_apply_overrides_handles_multiple_simultaneous():
    schedule_dict = {
        "nba-daily": {"task": NBA_TASK, "schedule": crontab(hour=3, minute=30)},
        "mlb-daily": {"task": MLB_TASK, "schedule": crontab(hour=14, minute=0)},
    }
    overrides = {
        "nba-daily": PipelineSchedule(
            beat_key="nba-daily",
            task_name=NBA_TASK,
            hour=5,
            minute=0,
            enabled=True,
        ),
        "mlb-daily": PipelineSchedule(
            beat_key="mlb-daily",
            task_name=MLB_TASK,
            hour=15,
            minute=30,
            enabled=False,
        ),
    }
    out = apply_overrides(schedule_dict, overrides)
    assert out["nba-daily"]["schedule"].hour == {5}
    assert "mlb-daily" not in out


def test_apply_overrides_mlb_daily_and_safety_net_independently():
    schedule_dict = {
        "mlb-projections-daily": {
            "task": MLB_TASK,
            "schedule": crontab(hour=14, minute=0),
        },
        "mlb-projections-safety-net": {
            "task": MLB_TASK,
            "schedule": crontab(hour=18, minute=0),
        },
    }
    overrides = {
        "mlb-projections-daily": PipelineSchedule(
            beat_key="mlb-projections-daily",
            task_name=MLB_TASK,
            hour=11,
            minute=0,
            enabled=True,
        ),
        "mlb-projections-safety-net": PipelineSchedule(
            beat_key="mlb-projections-safety-net",
            task_name=MLB_TASK,
            hour=18,
            minute=0,
            enabled=True,
        ),
    }
    out = apply_overrides(schedule_dict, overrides)
    assert out["mlb-projections-daily"]["schedule"].hour == {11}
    assert out["mlb-projections-safety-net"]["schedule"].hour == {18}
