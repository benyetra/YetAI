"""Admin pipeline schedule view.

Read-only in this PR: serializes celery_app.conf.beat_schedule into a
shape the admin calendar UI can render. The editable-schedules feature
will add PATCH endpoints + a DB-backed scheduler in a follow-up PR.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.celery_app import celery_app
from app.core.auth import require_admin
from app.services import pipeline_schedule_service as svc

router = APIRouter(prefix="/api/admin/pipelines", tags=["admin-pipelines"])


@router.get("/schedule")
async def get_schedule(_: dict = Depends(require_admin)):
    """Return today's pipeline schedule split into scheduled (crontab) and
    continuous (interval) entries, with next-fire timestamps in ET.

    The response is recomputed on each request; no caching needed at this
    scale (one admin page, ~16 entries).
    """
    return svc.serialize_schedule(dict(celery_app.conf.beat_schedule))
