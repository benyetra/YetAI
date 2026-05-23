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
from copy import deepcopy
from typing import Any

from celery.beat import PersistentScheduler
from celery.schedules import crontab

from app.core.database import SessionLocal
from app.data.celery_tasks import PIPELINE_ENQUEUE_CATALOG
from app.services import pipeline_schedule_overrides as ovr

logger = logging.getLogger(__name__)


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
        override = overrides.get(task_name) if task_name else None

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
