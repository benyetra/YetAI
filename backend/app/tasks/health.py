"""Health tasks: wiring ping, and the yetai_bets queue watch."""

import logging
import os
from datetime import datetime, timedelta

from app.celery_app import BETS_QUEUE, celery_app

log = logging.getLogger(__name__)

WATCH_TASK_NAME = "app.tasks.health.bets_queue_watch"
# Healthy depth is 0-2 (a run every 5-15 min, each seconds long). Nothing consuming
# the queue adds ~22 messages an hour (settle 4, expire 12, close capture 6).
BACKLOG_ALERT_DEPTH = int(os.getenv("YETAI_BETS_QUEUE_ALERT_DEPTH", "12"))
REALERT_AFTER = timedelta(hours=6)


@celery_app.task(name="app.tasks.health.ping")
def ping() -> dict:
    """Confirms Celery wiring. Invokable via celery.send_task or .apply()."""
    return {"status": "ok", "ts": datetime.utcnow().isoformat() + "Z"}


def bets_queue_depth() -> int:
    """Messages waiting on the yetai_bets queue (kombu's Redis list is the queue name)."""
    import redis

    from app.core.redis_broker import pick_redis_url

    client = redis.Redis.from_url(pick_redis_url(), socket_timeout=10)
    return int(client.llen(BETS_QUEUE))


@celery_app.task(name=WATCH_TASK_NAME)
def bets_queue_watch() -> dict:
    """Runs on the default queue every 10 min: alert when the bets queue backs up,
    i.e. no worker consumes it or it is stuck. At most one alert per 6h."""
    from app.core.database import SessionLocal
    from app.tasks.yetai_settlement_alert import _enabled, _last_alert, _send

    depth = bets_queue_depth()
    out = {"queue": BETS_QUEUE, "depth": depth, "sent": False}
    if depth < BACKLOG_ALERT_DEPTH or not _enabled():
        return out
    log.warning("%s backlog: %s messages waiting", BETS_QUEUE, depth)
    db = SessionLocal()
    try:
        last = _last_alert(db, WATCH_TASK_NAME)
        if last and datetime.utcnow() - last.created_at < REALERT_AFTER:
            return out
        _send(
            db,
            f"[YetAI Bets] {depth} tasks waiting on the {BETS_QUEUE} queue: "
            "is the bets worker running?",
            f"backlog:{depth}",
            task_name=WATCH_TASK_NAME,
            label="YetAI bets queue watch",
        )
        out["sent"] = True
        return out
    finally:
        db.close()
