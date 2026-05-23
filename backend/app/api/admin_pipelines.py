"""Admin pipeline schedule view + edit.

GET returns the live schedule with admin overrides applied and per-entry
flags (is_overridden, is_enabled). PATCH upserts an override row; POST
.../reset deletes it. The DatabaseScheduler picks up changes within ~30s.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.auth import require_admin
from app.core.database import get_db
from app.core.db_scheduler import apply_overrides
from app.services import pipeline_schedule_overrides as ovr
from app.services import pipeline_schedule_service as svc

router = APIRouter(prefix="/api/admin/pipelines", tags=["admin-pipelines"])


class UpdateScheduleRequest(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    enabled: bool = True


@router.get("/schedule")
async def get_schedule(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return today's pipeline schedule, with admin overrides applied and
    each entry flagged with is_overridden / is_enabled.

    Note: the API process reads `celery_app.conf.beat_schedule` (the
    hardcoded defaults) and applies overrides in-process. The Celery beat
    worker maintains its own copy that gets refreshed by DatabaseScheduler.
    """
    overrides = ovr.load_all(db)
    merged = apply_overrides(dict(celery_app.conf.beat_schedule), overrides)
    return svc.serialize_schedule(merged, overrides=overrides)


# task_name uses `:path` so dotted task names like
# "app.tasks.etl_pipeline.run_nba_update_pipeline" come through intact.
@router.patch("/{task_name:path}/schedule")
async def update_schedule(
    task_name: str,
    payload: UpdateScheduleRequest,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = ovr.upsert(
        db,
        task_name=task_name,
        hour=payload.hour,
        minute=payload.minute,
        enabled=payload.enabled,
        user_id=admin.get("id") or admin.get("user_id"),
    )
    return {
        "task_name": row.task_name,
        "hour": row.hour,
        "minute": row.minute,
        "enabled": row.enabled,
    }


@router.post("/{task_name:path}/schedule/reset")
async def reset_schedule(
    task_name: str,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not ovr.is_editable(task_name):
        raise HTTPException(
            status_code=400, detail=f"task_name not editable: {task_name}"
        )
    deleted = ovr.delete(db, task_name)
    return {"reset": deleted}
