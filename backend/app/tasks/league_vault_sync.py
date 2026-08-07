"""
Celery tasks: keep League Vault public sites current with platform data.
"""

from __future__ import annotations

import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.league_vault_sync.sync_all_vault_sites",
    ignore_result=False,
)
def sync_all_vault_sites() -> dict:
    """Weekly: re-ingest every public vault site, then force-recompute records."""
    from app.core.database import SessionLocal
    from app.services.league_vault.sync.refresh import (
        auto_sync_enabled,
        refresh_all_public_sites,
    )

    if not auto_sync_enabled():
        logger.info("league_vault auto-sync skipped — LEAGUE_VAULT_AUTO_SYNC disabled")
        return {"status": "skipped", "reason": "disabled"}

    if SessionLocal is None:
        logger.error("league_vault auto-sync skipped — no database session factory")
        return {"status": "error", "reason": "no_db"}

    db = SessionLocal()
    try:
        summary = refresh_all_public_sites(db, reingest=True, force_compute=True)
        logger.info(
            "league_vault auto-sync done sites=%s ok=%s errors=%s",
            summary.get("sites"),
            summary.get("ok"),
            summary.get("errors"),
        )
        return {"status": "ok", **summary}
    except Exception:
        logger.exception("league_vault auto-sync failed")
        return {"status": "error"}
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.league_vault_sync.recompute_all_vault_sites",
    ignore_result=False,
)
def recompute_all_vault_sites() -> dict:
    """Force all-play + records without platform re-ingest (ops / backfill)."""
    from app.core.database import SessionLocal
    from app.services.league_vault.sync.refresh import refresh_all_public_sites

    if SessionLocal is None:
        return {"status": "error", "reason": "no_db"}

    db = SessionLocal()
    try:
        summary = refresh_all_public_sites(db, reingest=False, force_compute=True)
        return {"status": "ok", **summary}
    except Exception:
        logger.exception("league_vault recompute-all failed")
        return {"status": "error"}
    finally:
        db.close()
