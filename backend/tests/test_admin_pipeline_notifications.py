"""Tests for admin pipeline notification dispatch.

Verifies that the Celery signal handlers route only PIPELINE_ENQUEUE_CATALOG
tasks to the persistence layer, and that record_finished correctly maps
orchestrator return dicts to FINISHED / FAILED event types.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core import celery_signals
from app.models.database_models import AdminNotificationEvent
from app.services import admin_notification_service as ans


# ---------------------------------------------------------------------------
# Routing: signal handlers ignore non-pipeline tasks
# ---------------------------------------------------------------------------


def test_is_tracked_pipeline_recognizes_all_orchestrators():
    assert ans.is_tracked_pipeline("app.tasks.etl_pipeline.run_nba_update_pipeline")
    assert ans.is_tracked_pipeline("app.tasks.etl_pipeline.run_mlb_update_pipeline")
    assert ans.is_tracked_pipeline("app.tasks.etl_pipeline.run_wnba_update_pipeline")


def test_is_tracked_pipeline_rejects_leaf_tasks_and_unknowns():
    # nba.spread_projector IS in the catalog as a sub-task entry, so we use
    # a leaf task that's not exposed in PIPELINE_ENQUEUE_CATALOG.
    assert not ans.is_tracked_pipeline("app.tasks.etl_pipeline.nba.update_team_roster")
    assert not ans.is_tracked_pipeline("app.tasks.games_sync.sync_games_cache")
    assert not ans.is_tracked_pipeline("")
    assert not ans.is_tracked_pipeline("totally.made.up.task")


# ---------------------------------------------------------------------------
# record_finished: classifies return dicts correctly
# ---------------------------------------------------------------------------


def test_record_finished_returns_none_for_unknown_task():
    """Service must not write rows for non-pipeline tasks."""
    with patch.object(ans, "_persist") as persist:
        result = ans.record_finished(
            task_name="not.a.pipeline", task_id="abc", result={"status": "ok"}
        )
    assert result is None
    persist.assert_not_called()


def test_record_finished_emits_finished_when_status_ok():
    """status='ok' return dict → FINISHED event with duration in message."""
    with patch.object(ans, "_persist", return_value=None) as persist:
        ans.record_finished(
            task_name="app.tasks.etl_pipeline.run_nba_update_pipeline",
            task_id="task-1",
            result={"status": "ok", "duration_s": 234.6, "phases": []},
        )
    persist.assert_called_once()
    kwargs = persist.call_args.kwargs
    assert kwargs["event_type"] is AdminNotificationEvent.FINISHED
    assert kwargs["status"] == "ok"
    assert kwargs["duration_s"] == pytest.approx(234.6)
    # Message formats duration with :.0f → 234.6 rounds to 235.
    assert "235s" in kwargs["message"]


def test_record_finished_emits_failed_when_status_is_failure():
    """status='failed' in the return dict downgrades to FAILED, not FINISHED."""
    with patch.object(ans, "_persist", return_value=None) as persist:
        ans.record_finished(
            task_name="app.tasks.etl_pipeline.run_mlb_update_pipeline",
            task_id="task-2",
            result={"status": "failed", "duration_s": 12.0},
        )
    kwargs = persist.call_args.kwargs
    assert kwargs["event_type"] is AdminNotificationEvent.FAILED


def test_record_failed_uses_exception_message():
    """Unhandled exceptions take the exception's str() into the message."""
    exc = RuntimeError("redis broker unreachable")
    with patch.object(ans, "_persist", return_value=None) as persist:
        ans.record_failed(
            task_name="app.tasks.etl_pipeline.run_nfl_update_pipeline",
            task_id="task-3",
            exception=exc,
            traceback_str="<traceback>",
        )
    kwargs = persist.call_args.kwargs
    assert kwargs["event_type"] is AdminNotificationEvent.FAILED
    assert "redis broker unreachable" in kwargs["message"]
    assert kwargs["error_message"] == "redis broker unreachable"
    assert kwargs["error_traceback"] == "<traceback>"


# ---------------------------------------------------------------------------
# Signal handlers: skip non-pipeline tasks even when invoked directly
# ---------------------------------------------------------------------------


class _FakeTask:
    def __init__(self, name):
        self.name = name


def test_prerun_handler_skips_non_pipeline_tasks():
    """task_prerun for non-pipeline tasks must not call record_started."""
    with patch.object(ans, "record_started") as rs:
        celery_signals._on_pipeline_prerun(
            sender=_FakeTask("app.tasks.games_sync.sync_games_cache"),
            task_id="abc",
            task=_FakeTask("app.tasks.games_sync.sync_games_cache"),
        )
    rs.assert_not_called()


def test_prerun_handler_persists_for_orchestrators():
    """task_prerun for a known orchestrator must invoke record_started."""
    task = _FakeTask("app.tasks.etl_pipeline.run_nba_update_pipeline")
    with (
        patch.object(ans, "record_started", return_value=None) as rs,
        patch.object(celery_signals, "_publish") as pub,
    ):
        celery_signals._on_pipeline_prerun(sender=task, task_id="abc", task=task)
    rs.assert_called_once_with(
        task_name="app.tasks.etl_pipeline.run_nba_update_pipeline", task_id="abc"
    )
    # _publish only fires when record_started returns a row (non-None)
    pub.assert_not_called()


def test_postrun_handler_skips_when_state_is_failure():
    """task_postrun must not double-write when task_failure already handled."""
    task = _FakeTask("app.tasks.etl_pipeline.run_nba_update_pipeline")
    with patch.object(ans, "record_finished") as rf:
        celery_signals._on_pipeline_postrun(
            sender=task, task_id="abc", task=task, retval=None, state="FAILURE"
        )
    rf.assert_not_called()


def test_utc_iso_appends_z_for_naive_datetime():
    from datetime import datetime

    assert ans._utc_iso(datetime(2026, 6, 5, 14, 30, 0)) == "2026-06-05T14:30:00Z"
