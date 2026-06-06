"""Tests for pipeline_schedule_overrides + PipelineSchedule model."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.database_models import PipelineSchedule
from app.services import pipeline_schedule_overrides as ovr


def test_model_has_required_columns():
    cols = {c.name for c in PipelineSchedule.__table__.columns}
    assert cols == {
        "beat_key",
        "task_name",
        "minute",
        "hour",
        "enabled",
        "updated_at",
        "updated_by_user_id",
    }
    assert PipelineSchedule.__tablename__ == "pipeline_schedules"


def test_load_all_returns_dict_keyed_by_beat_key():
    db = MagicMock()
    row = MagicMock(
        beat_key="nba-update-pipeline-daily",
        task_name="app.tasks.etl_pipeline.run_nba_update_pipeline",
        hour=6,
        minute=15,
        enabled=True,
    )
    db.query.return_value.all.return_value = [row]
    out = ovr.load_all(db)
    assert "nba-update-pipeline-daily" in out
    assert out["nba-update-pipeline-daily"].hour == 6


def test_load_all_empty():
    db = MagicMock()
    db.query.return_value.all.return_value = []
    assert ovr.load_all(db) == {}


def test_resolve_beat_keys_accepts_beat_key():
    keys = ovr.resolve_beat_keys("mlb-projections-daily")
    assert keys == ["mlb-projections-daily"]


def test_resolve_beat_keys_rejects_non_orchestrator_beat_key():
    with pytest.raises(HTTPException) as exc:
        ovr.resolve_beat_keys("mlb-statcast-incremental")
    assert exc.value.status_code == 400


def test_resolve_beat_keys_legacy_task_name_returns_all_slots():
    keys = ovr.resolve_beat_keys("app.tasks.etl_pipeline.run_mlb_update_pipeline")
    assert "mlb-projections-daily" in keys
    assert "mlb-projections-safety-net" in keys


def test_upsert_schedule_id_rejects_unknown():
    with pytest.raises(HTTPException) as exc:
        ovr.upsert_schedule_id(
            MagicMock(),
            schedule_id="not.a.pipeline",
            hour=3,
            minute=30,
            enabled=True,
            user_id=1,
        )
    assert exc.value.status_code == 400


def test_upsert_validates_hour_minute_ranges():
    with pytest.raises(HTTPException):
        ovr.upsert(
            MagicMock(),
            beat_key="nba-update-pipeline-daily",
            task_name="app.tasks.etl_pipeline.run_nba_update_pipeline",
            hour=25,
            minute=0,
            enabled=True,
            user_id=1,
        )
    with pytest.raises(HTTPException):
        ovr.upsert(
            MagicMock(),
            beat_key="nba-update-pipeline-daily",
            task_name="app.tasks.etl_pipeline.run_nba_update_pipeline",
            hour=3,
            minute=60,
            enabled=True,
            user_id=1,
        )


def test_is_editable_only_for_catalog_orchestrators():
    assert ovr.is_editable("app.tasks.etl_pipeline.run_nba_update_pipeline")
    assert ovr.is_editable("app.tasks.etl_pipeline.run_mlb_update_pipeline")
    assert not ovr.is_editable("app.tasks.games_sync.sync_games_cache")
    assert not ovr.is_editable("")
    assert ovr.is_editable_beat_key("mlb-projections-daily")
    assert not ovr.is_editable_beat_key("mlb-statcast-incremental")
