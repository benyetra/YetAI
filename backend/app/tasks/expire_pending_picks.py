"""
Celery task: expire PENDING_APPROVAL auto-picks whose game has started.

Runs every 5 minutes via beat. If admin hasn't approved by tipoff/first-pitch,
the pick is marked rejected so it never appears in subscriber history.
"""

import logging
from datetime import datetime, timedelta

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.database_models import YetAIBet
from app.services.yetai_bets_service_db import clamp_yetai_result

log = logging.getLogger(__name__)

PENDING_STATUS = "pending_approval"
REJECTED_STATUS = "rejected"
STALE_HOURS = 24


@celery_app.task(name="auto_pick.expire_pending")
def expire_pending_picks() -> int:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        stale_cutoff = now - timedelta(hours=STALE_HOURS)
        pending = db.query(YetAIBet).filter(YetAIBet.status == PENDING_STATUS).all()
        expired = []
        for row in pending:
            if row.commence_time is not None and row.commence_time <= now:
                expired.append(row)
                continue
            if (
                row.commence_time is None
                and row.created_at
                and row.created_at <= stale_cutoff
            ):
                expired.append(row)
        for r in expired:
            r.status = REJECTED_STATUS
            r.result = clamp_yetai_result("Auto-expired (unapproved)")
        if expired:
            db.commit()
            log.info("rejected %s unapproved YetAI picks", len(expired))
        return len(expired)
    finally:
        db.close()
