"""API-side loop that expires unapproved YetAI picks every 5 minutes."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from app.services.expire_pending_picks import expire_unapproved_picks

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 300


def _auto_picks_enabled() -> bool:
    return os.getenv("AUTO_YETAI_PICKS_ENABLED", "false").lower() == "true"


class ExpirePendingScheduler:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        if not _auto_picks_enabled():
            logger.info("Expire-pending scheduler disabled (AUTO_YETAI_PICKS_ENABLED)")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())
        self._running = True
        logger.info("Expire-pending scheduler started (every %ss)", INTERVAL_SECONDS)

    async def stop(self) -> None:
        if not self._running:
            return
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._running = False
        logger.info("Expire-pending scheduler stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(expire_unapproved_picks)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("expire_unapproved_picks failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue


expire_pending_scheduler = ExpirePendingScheduler()


def init_expire_pending_scheduler() -> None:
    expire_pending_scheduler.start()


async def cleanup_expire_pending_scheduler() -> None:
    await expire_pending_scheduler.stop()
