"""Admin pipeline notifications API.

Read-side surface for the admin_notifications table populated by
celery_signals. Every route is admin-gated; read state is tracked
per-admin via admin_notification_reads.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.database import get_db
from app.services import admin_notification_service as ans

router = APIRouter(prefix="/api/admin/notifications", tags=["admin-notifications"])


@router.get("")
async def list_notifications(
    limit: int = 50,
    unread_only: bool = False,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Newest-first list of pipeline notifications visible to this admin."""
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    user_id = admin.get("id") or admin.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="cannot resolve admin user id")
    items = ans.list_for_admin(
        db, user_id=user_id, limit=limit, unread_only=unread_only
    )
    return {
        "notifications": [n.to_dict() for n in items],
        "unread_count": (
            sum(1 for n in items if not n.is_read)
            if unread_only is False
            else len(items)
        ),
    }


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_id = admin.get("id") or admin.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="cannot resolve admin user id")
    ok = ans.mark_read(db, notification_id=notification_id, user_id=user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_notifications_read(
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_id = admin.get("id") or admin.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="cannot resolve admin user id")
    n = ans.mark_all_read(db, user_id=user_id)
    return {"marked_read": n}
