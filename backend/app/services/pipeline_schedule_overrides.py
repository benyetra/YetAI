"""Admin-editable Celery beat schedule overrides.

Read/write helpers for the pipeline_schedules table. The DatabaseScheduler
calls load_all() once per sync; the REST router calls upsert() and delete().
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.data.celery_tasks import PIPELINE_ENQUEUE_CATALOG
from app.models.database_models import PipelineSchedule

_EDITABLE_TASKS: frozenset[str] = frozenset(
    e["task_name"] for e in PIPELINE_ENQUEUE_CATALOG
)


def is_editable_task(task_name: str) -> bool:
    """True if this Celery task is in PIPELINE_ENQUEUE_CATALOG."""
    return task_name in _EDITABLE_TASKS


def is_editable(task_name: str) -> bool:
    """Backward-compatible alias for tests and reset guard."""
    return is_editable_task(task_name)


def _beat_schedule() -> dict[str, dict[str, Any]]:
    return dict(celery_app.conf.beat_schedule)


def resolve_beat_keys(schedule_id: str) -> list[str]:
    """Resolve a URL path id to one or more beat_schedule keys.

    Accepts either a beat key (``mlb-projections-daily``) or a legacy Celery
    ``task_name`` (``app.tasks....``). Legacy task names with multiple beat
    entries update every matching slot with the same hour/minute.
    """
    schedule_id = schedule_id.strip()
    if not schedule_id:
        raise HTTPException(status_code=400, detail="schedule id is required")

    beat = _beat_schedule()

    if schedule_id in beat:
        task = beat[schedule_id].get("task") or ""
        if not is_editable_task(task):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Beat entry {schedule_id!r} is not an editable orchestrator "
                    f"(task {task!r})"
                ),
            )
        return [schedule_id]

    if is_editable_task(schedule_id):
        matches = [k for k, entry in beat.items() if entry.get("task") == schedule_id]
        if not matches:
            raise HTTPException(
                status_code=400,
                detail=f"No beat entry found for task_name: {schedule_id}",
            )
        return matches

    raise HTTPException(
        status_code=400,
        detail=(
            f"Unknown schedule id: {schedule_id}. Use a beat key "
            f"(e.g. mlb-projections-daily) or a catalog Celery task_name."
        ),
    )


def is_editable_beat_key(beat_key: str) -> bool:
    try:
        resolve_beat_keys(beat_key)
        return True
    except HTTPException:
        return False


def load_all(db: Session) -> dict[str, PipelineSchedule]:
    """All override rows keyed by beat_key. Empty dict if none."""
    rows = db.query(PipelineSchedule).all()
    return {r.beat_key: r for r in rows}


def get(db: Session, beat_key: str) -> Optional[PipelineSchedule]:
    return db.query(PipelineSchedule).filter_by(beat_key=beat_key).one_or_none()


def upsert(
    db: Session,
    *,
    beat_key: str,
    task_name: str,
    hour: int,
    minute: int,
    enabled: bool,
    user_id: Optional[int],
) -> PipelineSchedule:
    """Create or update the override row for a single beat entry."""
    if not 0 <= hour <= 23:
        raise HTTPException(status_code=400, detail="hour must be 0..23")
    if not 0 <= minute <= 59:
        raise HTTPException(status_code=400, detail="minute must be 0..59")

    row = db.query(PipelineSchedule).filter_by(beat_key=beat_key).one_or_none()
    if row is None:
        row = PipelineSchedule(beat_key=beat_key, task_name=task_name)
        db.add(row)
    row.task_name = task_name
    row.hour = hour
    row.minute = minute
    row.enabled = enabled
    row.updated_by_user_id = user_id
    db.commit()
    db.refresh(row)
    return row


def upsert_schedule_id(
    db: Session,
    *,
    schedule_id: str,
    hour: int,
    minute: int,
    enabled: bool,
    user_id: Optional[int],
) -> list[PipelineSchedule]:
    """Upsert one row per beat key resolved from schedule_id."""
    beat = _beat_schedule()
    keys = resolve_beat_keys(schedule_id)
    rows: list[PipelineSchedule] = []
    for key in keys:
        task_name = beat[key].get("task") or ""
        rows.append(
            upsert(
                db,
                beat_key=key,
                task_name=task_name,
                hour=hour,
                minute=minute,
                enabled=enabled,
                user_id=user_id,
            )
        )
    return rows


def delete(db: Session, schedule_id: str) -> bool:
    """Drop override row(s) for schedule_id; returns True if any were deleted."""
    keys = resolve_beat_keys(schedule_id)
    deleted = False
    for key in keys:
        row = db.query(PipelineSchedule).filter_by(beat_key=key).one_or_none()
        if row is None:
            continue
        db.delete(row)
        deleted = True
    if deleted:
        db.commit()
    return deleted
