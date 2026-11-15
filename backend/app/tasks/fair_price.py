"""Celery tasks for the fair-price shadow study (shadow only; see services/fair_price/shadow)."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="fair_price.shadow_flag")
def shadow_flag() -> dict:
    from app.services.fair_price import shadow

    return shadow.run()


@celery_app.task(name="fair_price.shadow_grade")
def shadow_grade() -> dict:
    try:
        from app.services.fair_price import grade

        return grade.run()
    except Exception as e:  # noqa: BLE001 - shadow jobs never raise
        log.exception("fair_price grade failed")
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


@celery_app.task(name="fair_price.fit_weights")
def fit_weights() -> dict:
    from app.core.database import SessionLocal

    from app.services.fair_price import shadow

    if not shadow.enabled():
        return {"status": "disabled"}
    db = SessionLocal()
    try:
        from app.services.fair_price import weights

        today_et = datetime.now(ZoneInfo("America/New_York")).date()
        return weights.refit(db, today_et)
    except Exception as e:  # noqa: BLE001
        log.exception("fair_price weight refit failed")
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}
    finally:
        db.close()
