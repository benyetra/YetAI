"""Expire PENDING_APPROVAL auto-picks whose game has started.

Used by the API process (every 5 minutes) and the Celery task (manual enqueue).
Keeping this off Beat stops a cheap SQL job from pinning the fat ETL child.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.database_models import YetAIBet
from app.services.yetai_bets_service_db import clamp_yetai_result

log = logging.getLogger(__name__)

PENDING_STATUS = "pending_approval"
REJECTED_STATUS = "rejected"
STALE_HOURS = 24
# Allow admin approval through in-progress games (matches live board window).
APPROVAL_GRACE_AFTER_TIPOFF = timedelta(hours=4)


def expire_unapproved_picks() -> int:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        stale_cutoff = now - timedelta(hours=STALE_HOURS)
        pending = db.query(YetAIBet).filter(YetAIBet.status == PENDING_STATUS).all()
        expired = []
        for row in pending:
            if row.commence_time is not None:
                tipoff = row.commence_time
                if tipoff.tzinfo is not None:
                    tipoff = tipoff.replace(tzinfo=None)
                if tipoff + APPROVAL_GRACE_AFTER_TIPOFF <= now:
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
