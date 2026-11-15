"""Custom Celery beat scheduler with admin-editable overrides.

Loads the hardcoded `beat_schedule` from `celery_app.conf` once at startup,
then overlays any rows present in the `pipeline_schedules` table (managed
by admins via the UI). Polls the DB every `sync_every` seconds.

Safety rails:
  - If the DB is unreachable, the merge step falls back to hardcoded
    defaults — beat keeps running.
  - Only tasks in PIPELINE_ENQUEUE_CATALOG can be overridden. Override
    rows for any other task name are silently ignored.
  - Orphan override rows (task name removed from code) are ignored too.
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from copy import deepcopy
from typing import Any

from celery.beat import PersistentScheduler
from celery.schedules import crontab

from app.core.database import SessionLocal
from app.data.celery_tasks import PIPELINE_ENQUEUE_CATALOG
from app.services import pipeline_schedule_overrides as ovr

logger = logging.getLogger(__name__)

# One beat sends; any other beat (a second worker started with --beat, or the old
# container during a Railway deploy overlap) sees the key held and sends nothing.
BEAT_LEADER_KEY = "yetai:beat:leader"
BEAT_LEADER_TTL_S = 90


_ORCHESTRATOR_NAMES: frozenset[str] = frozenset(
    e["task_name"] for e in PIPELINE_ENQUEUE_CATALOG
)


def apply_overrides(
    schedule_dict: dict[str, dict[str, Any]],
    overrides: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return a new schedule dict with admin overrides applied.

    Pure function — no Celery infrastructure, no DB. Easy to unit-test.

    Rules:
      - Override applies only when task_name is in PIPELINE_ENQUEUE_CATALOG
        AND there's an existing entry for that task_name.
      - `enabled=False` removes the entry from the merged schedule.
      - Override rows for unknown / non-orchestrator task names are ignored.
    """
    out: dict[str, dict[str, Any]] = {}
    for key, entry in schedule_dict.items():
        task_name = entry.get("task")
        override = overrides.get(key)

        # Skip overrides on non-orchestrator tasks entirely.
        if override is not None and task_name in _ORCHESTRATOR_NAMES:
            if not override.enabled:
                # Drop the entry; beat will not fire this task.
                continue
            new_entry = dict(entry)
            new_entry["schedule"] = crontab(hour=override.hour, minute=override.minute)
            out[key] = new_entry
        else:
            # Either no override, or task is not editable: keep as-is.
            out[key] = entry
    return out


class DatabaseScheduler(PersistentScheduler):
    """Celery beat scheduler that overlays `pipeline_schedules` on the
    hardcoded `beat_schedule`. Re-merges every 30 seconds so admin edits
    take effect quickly without a beat restart.
    """

    # PersistentScheduler default is 3 minutes; tighten so UI edits don't
    # feel laggy. 30s is well under a typical Celery task duration.
    sync_every = 30

    _hardcoded_schedule: dict[str, dict[str, Any]] = {}

    def setup_schedule(self) -> None:
        # Snapshot the hardcoded schedule before super applies it. We
        # re-apply overrides against this snapshot on every sync (rather
        # than mutating in place) so deletes revert cleanly.
        self._hardcoded_schedule = deepcopy(dict(self.app.conf.beat_schedule))
        self.app.conf.beat_schedule = self._load_merged()
        super().setup_schedule()

    def sync(self) -> None:
        """Called every `sync_every` seconds. Re-merge schedule from DB."""
        try:
            merged = self._load_merged()
            self.app.conf.beat_schedule = merged
            # `merge_inplace` is the standard PersistentScheduler hook for
            # updating the in-memory schedule entries from a new dict.
            self.merge_inplace(merged)
        except Exception:
            logger.exception("DatabaseScheduler.sync failed; keeping prior schedule")
        super().sync()

    # --- single-sender guard -------------------------------------------------

    _leader = None  # unknown until the first tick; logged on every change
    _leader_client = None
    _leader_token = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    def _redis(self):
        if self._leader_client is None:
            import redis

            from app.core.redis_broker import pick_redis_url

            self._leader_client = redis.Redis.from_url(
                pick_redis_url(), socket_timeout=5, socket_connect_timeout=5
            )
        return self._leader_client

    def _claim_leadership(self) -> bool:
        """SET NX with a TTL, refreshed every tick by the holder. Fails open: if
        Redis is unreachable nothing can be sent anyway, and beat must not go quiet
        because a lock read failed."""
        try:
            r = self._redis()
            token = self._leader_token.encode()
            if r.set(BEAT_LEADER_KEY, token, nx=True, ex=BEAT_LEADER_TTL_S):
                return True
            # ponytail: GET then EXPIRE is not atomic; a key that expires in between
            # costs at most one tick of a second sender. Lua script if that matters.
            if r.get(BEAT_LEADER_KEY) == token:
                r.expire(BEAT_LEADER_KEY, BEAT_LEADER_TTL_S)
                return True
            return False
        except Exception:
            logger.exception("beat leader check failed; sending anyway")
            return True

    def tick(self, *args, **kwargs):
        leader = self._claim_leadership()
        if leader != self._leader:
            logger.warning(
                "beat %s: %s %s",
                self._leader_token,
                "is the sender (holds" if leader else "is standby (another beat holds",
                BEAT_LEADER_KEY + ")",
            )
        self._leader = leader
        # Wake at least every TTL/3 so the holder refreshes the key in time.
        return min(super().tick(*args, **kwargs), BEAT_LEADER_TTL_S / 3)

    def apply_entry(self, entry, producer=None):
        if self._leader is False:
            logger.info("beat standby: not sending %s (%s)", entry.name, entry.task)
            return
        return super().apply_entry(entry, producer=producer)

    def close(self) -> None:
        try:
            r = self._redis()
            if r.get(BEAT_LEADER_KEY) == self._leader_token.encode():
                r.delete(BEAT_LEADER_KEY)  # hand over at once on a clean stop
        except Exception:
            logger.exception("beat leader release failed")
        super().close()

    def _load_merged(self) -> dict[str, dict[str, Any]]:
        """Return hardcoded ∪ DB overrides. Falls back if DB unreachable."""
        try:
            with SessionLocal() as db:
                overrides = ovr.load_all(db)
        except Exception:
            logger.exception(
                "DatabaseScheduler could not load overrides; "
                "using hardcoded defaults"
            )
            overrides = {}
        return apply_overrides(self._hardcoded_schedule, overrides)
