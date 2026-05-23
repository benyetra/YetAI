"""Admin-editable Celery beat schedule overrides.

Read/write helpers for the pipeline_schedules table. The DatabaseScheduler
calls load_all() once per sync; the REST router calls upsert() and delete().
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.data.celery_tasks import PIPELINE_ENQUEUE_CATALOG
from app.models.database_models import PipelineSchedule

_EDITABLE: frozenset[str] = frozenset(e["task_name"] for e in PIPELINE_ENQUEUE_CATALOG)


def is_editable(task_name: str) -> bool:
    """True if this Celery task is one of the 7 catalog orchestrators."""
    return task_name in _EDITABLE


def load_all(db: Session) -> dict[str, PipelineSchedule]:
    """All override rows keyed by task_name. Empty dict if none."""
    rows = db.query(PipelineSchedule).all()
    return {r.task_name: r for r in rows}


def get(db: Session, task_name: str) -> Optional[PipelineSchedule]:
    return db.query(PipelineSchedule).filter_by(task_name=task_name).one_or_none()


def upsert(
    db: Session,
    *,
    task_name: str,
    hour: int,
    minute: int,
    enabled: bool,
    user_id: Optional[int],
) -> PipelineSchedule:
    """Create or update the override row. Validates task_name + ranges."""
    if not is_editable(task_name):
        raise HTTPException(
            status_code=400,
            detail=f"task_name not in editable set: {task_name}",
        )
    if not 0 <= hour <= 23:
        raise HTTPException(status_code=400, detail="hour must be 0..23")
    if not 0 <= minute <= 59:
        raise HTTPException(status_code=400, detail="minute must be 0..59")

    row = db.query(PipelineSchedule).filter_by(task_name=task_name).one_or_none()
    if row is None:
        row = PipelineSchedule(task_name=task_name)
        db.add(row)
    row.hour = hour
    row.minute = minute
    row.enabled = enabled
    row.updated_by_user_id = user_id
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, task_name: str) -> bool:
    """Drop the override row; returns False if there wasn't one."""
    row = db.query(PipelineSchedule).filter_by(task_name=task_name).one_or_none()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
