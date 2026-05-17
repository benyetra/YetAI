"""
Live polling Celery tasks (Development-9gk).

Each scheduled task fires one polling cycle. The poller instance is a
module-level singleton kept alive across task invocations within the same
worker process — this preserves the per-game `_last_play_index` so we don't
re-process plays we've already evaluated. (If the worker restarts, state is
lost and we may briefly re-fire alerts for in-flight at-bats — acceptable
tradeoff for now; can move to Redis-backed state if duplicates become a
problem.)

Per Development-vir: no Discord alerts. `alert_callback` routes through
YetAI's notification path (Twilio for opted-in users, WebSocket for live UI).
"""
import asyncio
import logging
from typing import List, Optional

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

# Module-level singleton — survives across task invocations in the same worker.
_mlb_poller_singleton = None


def _get_mlb_poller():
    """Lazy-construct the MLB poller on first use (avoids import-time DB hit)."""
    global _mlb_poller_singleton
    if _mlb_poller_singleton is not None:
        return _mlb_poller_singleton

    from app.services.live_betting.mlb_live_poller import MLBLivePoller
    from app.services.live_betting.play_event_listener import PlayEventListener
    from app.services.live_betting.prop_watchlist import PropWatchlist
    from app.services.notification_router import route_prop_events  # see TODO below

    watchlist = PropWatchlist()
    watchlist.load_from_db()  # populates from pred_pikkit_bets / pred_pikkit_picks
    listener = PlayEventListener(watchlist)
    _mlb_poller_singleton = MLBLivePoller(
        watchlist=watchlist,
        listener=listener,
        alert_callback=route_prop_events,
    )
    logger.info("Constructed MLBLivePoller singleton")
    return _mlb_poller_singleton


@celery_app.task(name="app.tasks.live_pollers.poll_mlb_live", ignore_result=True)
def poll_mlb_live() -> dict:
    """One polling tick for MLB live games. Fires every 20s via Beat."""
    try:
        poller = _get_mlb_poller()
    except Exception:
        logger.exception("Failed to construct MLB poller — skipping tick")
        return {"status": "error", "phase": "construct"}

    try:
        asyncio.run(poller.tick())
        return {"status": "ok"}
    except Exception:
        logger.exception("MLB poll tick failed")
        return {"status": "error", "phase": "tick"}


@celery_app.task(name="app.tasks.live_pollers.poll_nhl_live", ignore_result=True)
def poll_nhl_live() -> dict:
    """One polling tick for NHL live games.

    NOT IMPLEMENTED yet. The YetiBets repo has NHL prediction generation but
    not a live NHL play-by-play poller (NHL props are typically pre-game).
    Wire up a real NHL poller when in-game NHL props become a product priority.
    """
    logger.debug("NHL live poll — no-op (not implemented)")
    return {"status": "noop", "reason": "not_implemented"}


@celery_app.task(name="app.tasks.live_pollers.refresh_prop_watchlist", ignore_result=True)
def refresh_prop_watchlist() -> dict:
    """Reload the prop watchlist from the DB. Fires every 5 minutes via Beat
    so newly-placed user props start being tracked promptly without the worker
    needing to be restarted."""
    try:
        poller = _get_mlb_poller()
        poller.watchlist.load_from_db()
        return {"status": "ok", "watched_keys": len(poller.watchlist)}
    except Exception:
        logger.exception("Watchlist refresh failed")
        return {"status": "error"}
