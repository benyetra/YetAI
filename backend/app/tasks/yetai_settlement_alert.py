"""Hourly alert for YetAI bets stuck unsettled or voided in the last 24h.

Delivery: an AdminNotification row (admin bell + websocket push via Redis) plus
Twilio SMS to admins who opted in (notification_settings.sms_enabled + phone),
the same opt-in the prop-alert router uses. Discord is out by policy.
The last-alert signature lives in that row's ``extra`` so it survives restarts.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.database_models import (
    AdminNotification,
    AdminNotificationEvent,
    User,
    YetAIBet,
)
from app.services.yetai_bets_demo import is_demo_yetai_bet

log = logging.getLogger(__name__)

TASK_NAME = "yetai_bets.settlement_alert"
STUCK_AFTER = timedelta(hours=float(os.getenv("YETAI_STUCK_ALERT_HOURS", "24")))
# Rows with no commence_time are given this long (plus STUCK_AFTER) from created_at.
NO_COMMENCE_GRACE = timedelta(hours=24)


def _enabled() -> bool:
    return os.getenv("YETAI_SETTLEMENT_ALERTS_ENABLED", "true").strip().lower() not in (
        "false",
        "0",
        "no",
        "off",
    )


def _now() -> datetime:
    return datetime.utcnow()


def _load_bets(db) -> list:
    since = _now() - timedelta(days=30)
    return (
        db.query(YetAIBet)
        .filter(
            (YetAIBet.status.in_(["active", "pending"]))
            | ((YetAIBet.status == "void") & (YetAIBet.settled_at >= since))
        )
        .all()
    )


def collect(bets, now: datetime, stuck_after: timedelta = STUCK_AFTER):
    """Return ([stuck_id], [(void_id, reason)]) ignoring demo rows."""
    stuck = []
    voids = []
    for b in bets:
        if is_demo_yetai_bet(b):
            continue
        if b.status in ("active", "pending"):
            if b.commence_time is not None:
                due = b.commence_time + stuck_after
            else:
                due = (b.created_at or now) + NO_COMMENCE_GRACE + stuck_after
            if due < now:
                stuck.append(str(b.id))
        elif (
            b.status == "void"
            and b.settled_at
            and b.settled_at >= now - timedelta(hours=24)
        ):
            voids.append((str(b.id), b.result or "no reason recorded"))
    return sorted(stuck), sorted(voids)


def _last_signature(db) -> Optional[str]:
    row = (
        db.query(AdminNotification)
        .filter(AdminNotification.task_name == TASK_NAME)
        .order_by(AdminNotification.id.desc())
        .first()
    )
    return (row.extra or {}).get("signature") if row else None


def _signature(stuck_ids: list, voids: list) -> str:
    return f"s:{','.join(stuck_ids)}|v:{','.join(i for i, _ in voids)}"


def _is_new(signature: str, last: Optional[str]) -> bool:
    """Alert only for ids the last alert did not list: a set that merely shrank
    (a bet settled, a void aged out of the 24h window) stays quiet."""
    if not last or "|v:" not in last:  # none yet, or the old count-based format
        return True
    ids = lambda sig: [
        set(p.split(",")) - {""} for p in sig[2:].split("|v:")
    ]  # noqa: E731
    return any(cur - before for cur, before in zip(ids(signature), ids(last)))


def _sms_targets(db) -> list[str]:
    phones = []
    for (settings,) in db.query(User.notification_settings).filter(
        User.is_admin.is_(True)
    ):
        s = settings or {}
        phone = s.get("phone") or s.get("phone_number") or s.get("sms_number")
        if s.get("sms_enabled") and phone:
            phones.append(str(phone))
    return phones


def _send(db, message: str, signature: str) -> None:
    row = AdminNotification(
        event_type=AdminNotificationEvent.FAILED,
        task_name=TASK_NAME,
        pipeline_label="YetAI settlement alert",
        sport="yetai",
        status="alert",
        message=message,
        extra={"signature": signature},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    try:
        from app.core.celery_signals import _publish

        _publish(row.id)
    except Exception:
        log.exception("settlement alert websocket publish failed (non-fatal)")
    try:
        from app.services.notification_router import _send_sms

        for phone in _sms_targets(db):
            asyncio.run(_send_sms(phone, message[:300]))
    except Exception:
        log.exception("settlement alert SMS failed (non-fatal)")


def build_message(stuck: int, voids: list) -> str:
    parts = []
    if stuck:
        parts.append(f"{stuck} stuck unsettled")
    if voids:
        parts.append(
            f"{len(voids)} voided: "
            + "; ".join(f"{i[:8]} ({r[:80]})" for i, r in voids[:5])
        )
    return "[YetAI Bets] " + " | ".join(parts)


@celery_app.task(name=TASK_NAME)
def settlement_alert() -> dict:
    if not _enabled():
        return {"sent": False, "reason": "disabled"}
    db = SessionLocal()
    try:
        stuck_ids, voids = collect(_load_bets(db), _now())
        stuck = len(stuck_ids)
        if not stuck and not voids:
            return {"sent": False, "stuck": 0, "voided": 0}
        signature = _signature(stuck_ids, voids)
        if not _is_new(signature, _last_signature(db)):
            return {"sent": False, "stuck": stuck, "voided": len(voids)}
        _send(db, build_message(stuck, voids), signature)
        return {"sent": True, "stuck": stuck, "voided": len(voids)}
    except Exception as e:
        log.exception("%s failed", TASK_NAME)
        return {"sent": False, "error": str(e)}
    finally:
        db.close()
