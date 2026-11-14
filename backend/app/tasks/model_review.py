"""Celery task: email the daily model review (beat runs it at 09:45 ET).

Recipients: MODEL_REVIEW_EMAIL_TO (comma-separated), else the emails of admin users.
Kill switch: MODEL_REVIEW_EMAIL_ENABLED=false. Email only (no Discord, see celery_app.py).
"""

import logging
import os
from datetime import datetime

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.database_models import User
from app.services.admin_notification_service import get_admin_user_ids
from app.services.auto_pick.candidate import utc_to_eastern
from app.services.email_service import EmailService
from app.services.model_review_service import build_review, render_html, render_text

log = logging.getLogger(__name__)


def email_enabled() -> bool:
    return os.getenv("MODEL_REVIEW_EMAIL_ENABLED", "true").strip().lower() == "true"


def _recipients(db) -> list[str]:
    raw = os.getenv("MODEL_REVIEW_EMAIL_TO", "")
    emails = [e.strip() for e in raw.split(",") if e.strip()]
    if emails:
        return emails
    ids = get_admin_user_ids(db)
    rows = db.query(User.email).filter(User.id.in_(ids)).all() if ids else []
    return [e for (e,) in rows if e]


@celery_app.task(name="model_review.daily")
def model_review_daily() -> dict:
    if not email_enabled():
        return {"sent": 0, "skipped": "MODEL_REVIEW_EMAIL_ENABLED=false"}
    db = SessionLocal()
    try:
        today = utc_to_eastern(datetime.utcnow()).date()
        review = build_review(db, today)
        html_body, text_body = render_html(review), render_text(review)
        to = _recipients(db)
        if not to:
            log.warning("model_review.daily: no recipients (set MODEL_REVIEW_EMAIL_TO)")
            return {"sent": 0, "skipped": "no recipients"}
        svc = EmailService()
        subject = f"YetAI model review {today.isoformat()}"
        sent = sum(
            bool(svc.send_email(addr, subject, html_body, text_body)) for addr in to
        )
        return {"sent": sent, "recipients": len(to)}
    except Exception as e:
        log.exception("model_review.daily failed")
        return {"sent": 0, "error": str(e)}
    finally:
        db.close()
