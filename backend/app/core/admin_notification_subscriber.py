"""Redis pub/sub subscriber that bridges Celery workers → WebSocket clients.

The Celery worker writes an AdminNotification row, then publishes the row's
id to ADMIN_NOTIFICATION_CHANNEL. This subscriber runs inside the FastAPI
process (started from the lifespan hook), receives those IDs, fetches the
row, and pushes the serialized notification to every connected admin's
WebSocket via the shared ConnectionManager.

If the Redis subscriber dies, REST polling on page load still works — the
DB row is the source of truth.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional

import redis.asyncio as aioredis
from sqlalchemy.orm import Session

from app.core.celery_signals import ADMIN_NOTIFICATION_CHANNEL
from app.core.database import SessionLocal
from app.core.redis_broker import pick_redis_url
from app.models.database_models import AdminNotification
from app.services import admin_notification_service as ans

logger = logging.getLogger(__name__)


# Type alias: (message: str, user_id: int) -> coroutine
SendFn = Callable[[str, int], Awaitable[None]]


class AdminNotificationSubscriber:
    """Background asyncio task that fans out new admin notifications to
    connected admin WebSockets.

    Usage:
        sub = AdminNotificationSubscriber(send_fn=ws_manager.send_personal_message)
        await sub.start()
        ...
        await sub.stop()
    """

    def __init__(self, send_fn: SendFn) -> None:
        self._send_fn = send_fn
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[aioredis.Redis] = None
        self._pubsub: Optional[Any] = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(
            self._run(), name="admin-notification-subscriber"
        )
        logger.info("admin notification subscriber started")

    async def stop(self) -> None:
        self._stopping.set()
        if self._pubsub is not None:
            try:
                await self._pubsub.close()
            except Exception:
                pass
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        logger.info("admin notification subscriber stopped")

    async def _run(self) -> None:
        """Subscribe loop. Reconnects on transient errors."""
        while not self._stopping.is_set():
            try:
                self._client = aioredis.from_url(pick_redis_url())
                self._pubsub = self._client.pubsub()
                await self._pubsub.subscribe(ADMIN_NOTIFICATION_CHANNEL)
                logger.info("subscribed to %s", ADMIN_NOTIFICATION_CHANNEL)
                async for raw in self._pubsub.listen():
                    if self._stopping.is_set():
                        break
                    if raw.get("type") != "message":
                        continue
                    await self._handle(raw.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "admin notification subscriber error; reconnecting in 5s"
                )
                await asyncio.sleep(5.0)

    async def _handle(self, data: Any) -> None:
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            payload = json.loads(data)
            nid = int(payload.get("notification_id"))
        except Exception:
            logger.exception("malformed admin notification pub/sub payload")
            return

        db: Session = SessionLocal()
        try:
            notif = db.query(AdminNotification).filter_by(id=nid).first()
            if notif is None:
                logger.warning("admin notification %d not found; skipping fan-out", nid)
                return
            admin_ids = ans.get_admin_user_ids(db)
            serialized = ans.serialize_for_websocket(notif)
        finally:
            db.close()

        if not admin_ids:
            return

        for uid in admin_ids:
            try:
                await self._send_fn(serialized, uid)
            except Exception:
                logger.debug("fan-out to user %d failed (likely disconnected)", uid)
