"""Celery task: settle shown YetAI Bets (beat runs it every 15 minutes)."""

import logging

from app.celery_app import celery_app
from app.services.yetai_bets_service_db import YetAIBetsServiceDB

log = logging.getLogger(__name__)


@celery_app.task(name="yetai_bets.settle")
def settle_yetai_bets() -> dict:
    try:
        return YetAIBetsServiceDB().verify_pending_yetai_bets()
    except Exception as e:
        log.exception("yetai_bets.settle failed")
        return {"success": False, "error": str(e)}
