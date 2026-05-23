"""Celery signal handlers for admin pipeline notifications.

Wired into the worker process: on start / success / failure of any of the 7
PIPELINE_ENQUEUE_CATALOG orchestrators, write a row to admin_notifications
and publish a Redis pub/sub message so the API process can fan it out over
WebSocket to connected admins.

Module-level signal connections run on import — celery_app.py imports this
module unconditionally so the worker registers them at boot.
"""

from __future__ import annotations

import json
import logging
import traceback as _tb_mod
from typing import Any, Optional

import redis
from celery.signals import task_failure, task_postrun, task_prerun

from app.core.redis_broker import pick_redis_url
from app.services import admin_notification_service as ans

logger = logging.getLogger(__name__)

# Pub/sub channel name. The API process subscribes to this on startup.
ADMIN_NOTIFICATION_CHANNEL = "yetai.admin_notifications"


def _publish(notification_id: int) -> None:
    """Best-effort publish of a new notification ID.

    The API process listens on ADMIN_NOTIFICATION_CHANNEL, fetches the row,
    and fans out to connected admins. We use a single new Redis client per
    publish (rare events, ~tens per day) instead of a long-lived connection
    so worker process crashes don't strand sockets.
    """
    try:
        client = redis.Redis.from_url(pick_redis_url())
        client.publish(
            ADMIN_NOTIFICATION_CHANNEL,
            json.dumps({"notification_id": notification_id}),
        )
    except Exception:
        # Live push is a best-effort UX enhancement; persistence still works.
        logger.exception("admin notification redis publish failed")


@task_prerun.connect
def _on_pipeline_prerun(
    sender: Any = None,
    task_id: Optional[str] = None,
    task: Any = None,
    **_: Any,
) -> None:
    task_name = getattr(task, "name", None) or getattr(sender, "name", None)
    if not task_name or not ans.is_tracked_pipeline(task_name):
        return
    notif = ans.record_started(task_name=task_name, task_id=task_id)
    if notif is not None:
        _publish(notif.id)


@task_postrun.connect
def _on_pipeline_postrun(
    sender: Any = None,
    task_id: Optional[str] = None,
    task: Any = None,
    retval: Any = None,
    state: Optional[str] = None,
    **_: Any,
) -> None:
    """Fires on every task return (success or failure path that doesn't raise).

    The orchestrators we care about return a dict like
    {"status": "ok"|"failed", "duration_s": ..., ...} on completion, so we
    classify via that. If the task raised, task_failure fires instead and
    state will be "FAILURE" here too — but we let task_failure own that path
    so we don't double-write.
    """
    if state == "FAILURE":
        return
    task_name = getattr(task, "name", None) or getattr(sender, "name", None)
    if not task_name or not ans.is_tracked_pipeline(task_name):
        return
    notif = ans.record_finished(task_name=task_name, task_id=task_id, result=retval)
    if notif is not None:
        _publish(notif.id)


@task_failure.connect
def _on_pipeline_failure(
    sender: Any = None,
    task_id: Optional[str] = None,
    exception: Optional[BaseException] = None,
    traceback: Any = None,
    einfo: Any = None,
    **_: Any,
) -> None:
    task_name = getattr(sender, "name", None)
    if not task_name or not ans.is_tracked_pipeline(task_name):
        return
    tb_str: Optional[str] = None
    if einfo is not None and hasattr(einfo, "traceback"):
        tb_str = str(einfo.traceback)
    elif traceback is not None:
        try:
            tb_str = "".join(_tb_mod.format_tb(traceback))
        except Exception:
            tb_str = None
    notif = ans.record_failed(
        task_name=task_name,
        task_id=task_id,
        exception=exception,
        traceback_str=tb_str,
    )
    if notif is not None:
        _publish(notif.id)
