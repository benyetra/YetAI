"""
Celery task: sync Odds API games + ESPN broadcast info into the games table.

Popular-games reads from this cache. After the YetiBets → YetAI merge, only Celery
Beat runs recurring jobs on Railway — the in-process scheduler on the API dyno is
not reliable as the sole sync path.
"""

import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.games_sync.sync_games_cache", ignore_result=False)
def sync_games_cache() -> dict:
    """Populate/update the games table from Odds API + ESPN broadcast data."""
    from app.core.config import settings

    if not settings.ODDS_API_KEY:
        logger.warning(
            "sync_games_cache skipped — no resolved odds API key: %s",
            settings.odds_api_env_diagnostics(),
        )
        return {"status": "skipped", "reason": "no_odds_api_key"}

    from app.services.games_sync_service import run_games_sync

    try:
        stats = asyncio.run(run_games_sync())
        logger.info(
            "Games cache sync: fetched=%s created=%s updated=%s",
            stats.get("total_games_fetched"),
            stats.get("total_games_created"),
            stats.get("total_games_updated"),
        )
        return {"status": "ok", **stats}
    except Exception:
        logger.exception("Games cache sync failed")
        return {"status": "error"}
