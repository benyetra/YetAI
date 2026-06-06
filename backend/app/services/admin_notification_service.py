"""Service for admin Celery pipeline notifications.

Single source of truth for creating, listing, and marking-read
AdminNotification rows. Used by:
  - app.core.celery_signals (writers, in the worker process)
  - app.api.admin_notifications (REST readers, in the API process)
  - app.core.celery_signals_publisher (Redis pub/sub bridge to API)

Read state is per-admin (admin_notification_reads join table).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.data.celery_tasks import PIPELINE_ENQUEUE_CATALOG
from app.models.database_models import (
    AdminNotification,
    AdminNotificationEvent,
    AdminNotificationRead,
    User,
)

logger = logging.getLogger(__name__)


# task_name -> display label, sourced from PIPELINE_ENQUEUE_CATALOG so a
# pipeline added to the catalog automatically gets a friendly label.
_PIPELINE_LABELS: dict[str, str] = {
    entry["task_name"]: entry["label"] for entry in PIPELINE_ENQUEUE_CATALOG
}
_PIPELINE_SPORTS: dict[str, str] = {
    entry["task_name"]: entry.get("sport", "")
    for entry in PIPELINE_ENQUEUE_CATALOG
    if entry.get("sport")
}

PIPELINE_TASK_NAMES: frozenset[str] = frozenset(_PIPELINE_LABELS.keys())


@dataclass
class NotificationDTO:
    """Wire format returned by the REST endpoints and pushed over WebSocket.

    `is_read` is resolved per-admin at query time via the join table.
    """

    id: int
    event_type: str
    task_name: str
    pipeline_label: str
    sport: Optional[str]
    task_id: Optional[str]
    status: Optional[str]
    duration_s: Optional[float]
    message: str
    error_message: Optional[str]
    extra: dict
    created_at: str
    is_read: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_tracked_pipeline(task_name: str) -> bool:
    """True if Celery task_name is one of the orchestrators we notify on."""
    return task_name in PIPELINE_TASK_NAMES


def label_for(task_name: str) -> str:
    """Human label for the pipeline; falls back to bare task name."""
    return _PIPELINE_LABELS.get(task_name, task_name)


def sport_for(task_name: str) -> Optional[str]:
    return _PIPELINE_SPORTS.get(task_name)


# ---------------------------------------------------------------------------
# Writers (worker side)
# ---------------------------------------------------------------------------


def record_started(
    *,
    task_name: str,
    task_id: Optional[str],
) -> Optional[AdminNotification]:
    """Persist a 'started' event. Returns None if task is not tracked."""
    if not is_tracked_pipeline(task_name):
        return None
    label = label_for(task_name)
    return _persist(
        event_type=AdminNotificationEvent.STARTED,
        task_name=task_name,
        task_id=task_id,
        message=f"{label} started",
    )


def record_finished(
    *,
    task_name: str,
    task_id: Optional[str],
    result: Any,
) -> Optional[AdminNotification]:
    """Persist a 'finished' event for a successful orchestrator return.

    The orchestrator's return dict usually contains:
      {status, sport, started_at, finished_at, duration_s, failed_tasks,
       critical_failed_tasks, phases, ...}
    If `status` indicates failure, classify as FAILED instead of FINISHED.
    """
    if not is_tracked_pipeline(task_name):
        return None
    label = label_for(task_name)

    status = None
    duration_s = None
    extra: dict = {}
    if isinstance(result, dict):
        status = str(result.get("status")) if result.get("status") else None
        duration_s = _coerce_float(result.get("duration_s"))
        extra = {
            k: v
            for k, v in result.items()
            if k
            in {
                "started_at",
                "finished_at",
                "duration_s",
                "failed_tasks",
                "critical_failed_tasks",
                "phases",
                "status",
            }
        }

    is_failure_status = status in {"failed", "error", "critical_failed"}
    event = (
        AdminNotificationEvent.FAILED
        if is_failure_status
        else AdminNotificationEvent.FINISHED
    )

    if event is AdminNotificationEvent.FAILED:
        message = f"{label} reported failure ({status})"
        if duration_s is not None:
            message += f" after {duration_s:.0f}s"
    else:
        message = f"{label} finished"
        if duration_s is not None:
            message += f" in {duration_s:.0f}s"

    return _persist(
        event_type=event,
        task_name=task_name,
        task_id=task_id,
        status=status,
        duration_s=duration_s,
        message=message,
        extra=extra,
    )


def record_failed(
    *,
    task_name: str,
    task_id: Optional[str],
    exception: Optional[BaseException],
    traceback_str: Optional[str],
) -> Optional[AdminNotification]:
    """Persist a 'failed' event for an unhandled exception."""
    if not is_tracked_pipeline(task_name):
        return None
    label = label_for(task_name)
    err_msg = str(exception) if exception else "unknown error"
    return _persist(
        event_type=AdminNotificationEvent.FAILED,
        task_name=task_name,
        task_id=task_id,
        status="exception",
        message=f"{label} failed: {err_msg[:200]}",
        error_message=err_msg,
        error_traceback=traceback_str,
    )


def _persist(
    *,
    event_type: AdminNotificationEvent,
    task_name: str,
    task_id: Optional[str],
    message: str,
    status: Optional[str] = None,
    duration_s: Optional[float] = None,
    error_message: Optional[str] = None,
    error_traceback: Optional[str] = None,
    extra: Optional[dict] = None,
) -> Optional[AdminNotification]:
    """Single insert path. Swallows DB errors so notification failures never
    take down a pipeline run.
    """
    db = SessionLocal()
    try:
        notif = AdminNotification(
            event_type=event_type,
            task_name=task_name,
            pipeline_label=label_for(task_name),
            sport=sport_for(task_name),
            task_id=task_id,
            status=status,
            duration_s=duration_s,
            message=message,
            error_message=error_message,
            error_traceback=error_traceback,
            extra=extra or {},
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif
    except Exception as e:
        db.rollback()
        logger.exception("Failed to persist admin notification: %s", e)
        return None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Readers (API side)
# ---------------------------------------------------------------------------


def list_for_admin(
    db: Session,
    *,
    user_id: int,
    limit: int = 50,
    unread_only: bool = False,
) -> list[NotificationDTO]:
    """Return notifications for an admin, newest first, with per-admin read state."""
    q = db.query(AdminNotification).order_by(AdminNotification.created_at.desc())
    if unread_only:
        read_ids = db.query(AdminNotificationRead.notification_id).filter(
            AdminNotificationRead.user_id == user_id
        )
        q = q.filter(~AdminNotification.id.in_(read_ids))
    rows = q.limit(limit).all()

    if not rows:
        return []

    read_set = set(
        nid
        for (nid,) in db.query(AdminNotificationRead.notification_id)
        .filter(AdminNotificationRead.user_id == user_id)
        .filter(AdminNotificationRead.notification_id.in_([r.id for r in rows]))
        .all()
    )

    return [_to_dto(r, is_read=r.id in read_set) for r in rows]


def mark_read(db: Session, *, notification_id: int, user_id: int) -> bool:
    """Idempotent upsert of a read receipt. Returns True if the notification exists."""
    exists = db.query(AdminNotification.id).filter_by(id=notification_id).first()
    if not exists:
        return False
    stmt = (
        pg_insert(AdminNotificationRead)
        .values(notification_id=notification_id, user_id=user_id)
        .on_conflict_do_nothing()
    )
    db.execute(stmt)
    db.commit()
    return True


def mark_all_read(db: Session, *, user_id: int) -> int:
    """Mark every currently-unread notification as read for this admin. Returns count."""
    unread = (
        db.query(AdminNotification.id)
        .filter(
            ~AdminNotification.id.in_(
                db.query(AdminNotificationRead.notification_id).filter(
                    AdminNotificationRead.user_id == user_id
                )
            )
        )
        .all()
    )
    if not unread:
        return 0
    stmt = pg_insert(AdminNotificationRead).values(
        [{"notification_id": nid, "user_id": user_id} for (nid,) in unread]
    )
    db.execute(stmt.on_conflict_do_nothing())
    db.commit()
    return len(unread)


def get_admin_user_ids(db: Session) -> list[int]:
    """All admin user IDs, for WebSocket fan-out."""
    return [uid for (uid,) in db.query(User.id).filter(User.is_admin.is_(True)).all()]


def _utc_iso(dt: Optional[datetime]) -> str:
    """Serialize UTC datetimes with an explicit Z suffix for JS clients."""
    value = dt or datetime.utcnow()
    text = value.isoformat()
    if text.endswith("Z") or text.endswith("+00:00") or "+" in text[10:]:
        return text
    return f"{text}Z"


def _to_dto(row: AdminNotification, *, is_read: bool) -> NotificationDTO:
    return NotificationDTO(
        id=row.id,
        event_type=(
            row.event_type.value
            if hasattr(row.event_type, "value")
            else str(row.event_type)
        ),
        task_name=row.task_name,
        pipeline_label=row.pipeline_label,
        sport=row.sport,
        task_id=row.task_id,
        status=row.status,
        duration_s=row.duration_s,
        message=row.message,
        error_message=row.error_message,
        extra=row.extra or {},
        created_at=_utc_iso(row.created_at),
        is_read=is_read,
    )


def _coerce_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def serialize_for_websocket(notif: AdminNotification) -> str:
    """Encode a notification for WebSocket push. is_read is omitted; the client
    sees these as freshly-arrived and treats them as unread.
    """
    dto = _to_dto(notif, is_read=False)
    return json.dumps({"type": "admin_notification", **dto.to_dict()})
