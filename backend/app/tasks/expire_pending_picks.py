"""
Celery task: expire PENDING_APPROVAL auto-picks whose game has started.

Runs every 5 minutes via beat. If admin hasn't approved by tipoff/first-pitch,
the pick auto-flips to EXPIRED so it cannot retroactively appear live.
"""
import logging
from datetime import datetime

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.database_models import YetAIBet

log = logging.getLogger(__name__)

PENDING_STATUS = "pending_approval"
EXPIRED_STATUS = "expired"


@celery_app.task(name="auto_pick.expire_pending")
def expire_pending_picks() -> int:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        rows = (
            db.query(YetAIBet)
            .filter(YetAIBet.status == PENDING_STATUS)
            .filter(YetAIBet.commence_time.isnot(None))
            .filter(YetAIBet.commence_time <= now)
            .all()
        )
        for r in rows:
            r.status = EXPIRED_STATUS
        if rows:
            db.commit()
            log.info("expired %s pending YetAI picks", len(rows))
        return len(rows)
    finally:
        db.close()
