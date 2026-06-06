"""Admin pipeline schedule view + edit.

GET returns the live schedule with admin overrides applied and per-entry
flags (is_overridden, is_enabled). PATCH upserts an override row; POST
.../reset deletes it. The DatabaseScheduler picks up changes within ~30s.
"""

from __future__ import annotations

import os

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
    body = svc.serialize_schedule(merged, overrides=overrides)
    body["auto_yetai_picks_enabled"] = (
        os.getenv("AUTO_YETAI_PICKS_ENABLED", "false").lower() == "true"
    )
    return body


# schedule_id: beat key (mlb-projections-daily) or legacy Celery task_name.
@router.patch("/{schedule_id:path}/schedule")
async def update_schedule(
    schedule_id: str,
    payload: UpdateScheduleRequest,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = ovr.upsert_schedule_id(
        db,
        schedule_id=schedule_id,
        hour=payload.hour,
        minute=payload.minute,
        enabled=payload.enabled,
        user_id=admin.get("id") or admin.get("user_id"),
    )
    row = rows[-1]
    return {
        "beat_key": row.beat_key,
        "task_name": row.task_name,
        "hour": row.hour,
        "minute": row.minute,
        "enabled": row.enabled,
        "updated_keys": [r.beat_key for r in rows],
    }


@router.post("/{schedule_id:path}/schedule/reset")
async def reset_schedule(
    schedule_id: str,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        ovr.resolve_beat_keys(schedule_id)
    except HTTPException:
        raise
    deleted = ovr.delete(db, schedule_id)
    return {"reset": deleted}
