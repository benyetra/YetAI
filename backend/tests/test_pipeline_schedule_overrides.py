"""Tests for pipeline_schedule_overrides + PipelineSchedule model."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.database_models import PipelineSchedule
from app.services import pipeline_schedule_overrides as ovr


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_model_has_required_columns():
    cols = {c.name for c in PipelineSchedule.__table__.columns}
    assert cols == {
        "task_name",
        "minute",
        "hour",
        "enabled",
        "updated_at",
        "updated_by_user_id",
    }
    assert PipelineSchedule.__tablename__ == "pipeline_schedules"


# ---------------------------------------------------------------------------
# load_all
# ---------------------------------------------------------------------------


def test_load_all_returns_dict_keyed_by_task_name():
    db = MagicMock()
    row = MagicMock(
        task_name="app.tasks.etl_pipeline.run_nba_update_pipeline",
        hour=6,
        minute=15,
        enabled=True,
    )
    db.query.return_value.all.return_value = [row]
    out = ovr.load_all(db)
    assert "app.tasks.etl_pipeline.run_nba_update_pipeline" in out
    assert out["app.tasks.etl_pipeline.run_nba_update_pipeline"].hour == 6


def test_load_all_empty():
    db = MagicMock()
    db.query.return_value.all.return_value = []
    assert ovr.load_all(db) == {}


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------


def test_upsert_rejects_unknown_task_name():
    with pytest.raises(HTTPException) as exc:
        ovr.upsert(
            MagicMock(),
            task_name="not.a.pipeline",
            hour=3,
            minute=30,
            enabled=True,
            user_id=1,
        )
    assert exc.value.status_code == 400


def test_upsert_validates_hour_minute_ranges():
    name = "app.tasks.etl_pipeline.run_nba_update_pipeline"
    with pytest.raises(HTTPException):
        ovr.upsert(
            MagicMock(),
            task_name=name,
            hour=25,
            minute=0,
            enabled=True,
            user_id=1,
        )
    with pytest.raises(HTTPException):
        ovr.upsert(
            MagicMock(),
            task_name=name,
            hour=3,
            minute=60,
            enabled=True,
            user_id=1,
        )


def test_is_editable_only_for_catalog_orchestrators():
    assert ovr.is_editable("app.tasks.etl_pipeline.run_nba_update_pipeline")
    assert ovr.is_editable("app.tasks.etl_pipeline.run_mlb_update_pipeline")
    assert not ovr.is_editable("app.tasks.live_pollers.poll_mlb_live")
    assert not ovr.is_editable("")
