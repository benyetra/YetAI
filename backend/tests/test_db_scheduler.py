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
    override = PipelineSchedule(task_name=NBA_TASK, hour=6, minute=15, enabled=True)
    out = apply_overrides(schedule_dict, {NBA_TASK: override})

    new_cron = out["nba-daily"]["schedule"]
    assert new_cron.hour == {6}
    assert new_cron.minute == {15}
    # Original input untouched (no in-place mutation).
    assert schedule_dict["nba-daily"]["schedule"].hour == {3}


def test_apply_overrides_removes_entry_when_disabled():
    """enabled=False removes the entry — beat won't fire it."""
    schedule_dict = {
        "nba-daily": {"task": NBA_TASK, "schedule": crontab(hour=3, minute=30)}
    }
    override = PipelineSchedule(task_name=NBA_TASK, hour=6, minute=15, enabled=False)
    out = apply_overrides(schedule_dict, {NBA_TASK: override})
    assert "nba-daily" not in out


def test_apply_overrides_ignores_orphan_overrides():
    """Override for a task that no longer exists in beat_schedule is ignored."""
    schedule_dict = {
        "nba-daily": {"task": NBA_TASK, "schedule": crontab(hour=3, minute=30)}
    }
    orphan = PipelineSchedule(
        task_name="some.removed.task", hour=6, minute=15, enabled=True
    )
    out = apply_overrides(schedule_dict, {"some.removed.task": orphan})
    assert out == schedule_dict


def test_apply_overrides_skips_non_orchestrator_tasks():
    """Live pollers etc. are never overridden, even if a row exists."""
    schedule_dict = {
        "mlb-poll": {
            "task": "app.tasks.live_pollers.poll_mlb_live",
            "schedule": 20.0,
        },
    }
    override = PipelineSchedule(
        task_name="app.tasks.live_pollers.poll_mlb_live",
        hour=6,
        minute=15,
        enabled=True,
    )
    out = apply_overrides(
        schedule_dict, {"app.tasks.live_pollers.poll_mlb_live": override}
    )
    assert out["mlb-poll"]["schedule"] == 20.0


def test_apply_overrides_handles_multiple_simultaneous():
    schedule_dict = {
        "nba-daily": {"task": NBA_TASK, "schedule": crontab(hour=3, minute=30)},
        "mlb-daily": {"task": MLB_TASK, "schedule": crontab(hour=14, minute=0)},
    }
    overrides = {
        NBA_TASK: PipelineSchedule(task_name=NBA_TASK, hour=5, minute=0, enabled=True),
        MLB_TASK: PipelineSchedule(
            task_name=MLB_TASK, hour=15, minute=30, enabled=False
        ),
    }
    out = apply_overrides(schedule_dict, overrides)
    assert out["nba-daily"]["schedule"].hour == {5}
    assert "mlb-daily" not in out
