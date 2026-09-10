"""Celery wrapper for expire_unapproved_picks (manual / admin enqueue only)."""

from app.celery_app import celery_app
from app.services.expire_pending_picks import expire_unapproved_picks


@celery_app.task(name="auto_pick.expire_pending")
def expire_pending_picks() -> int:
    return expire_unapproved_picks()
