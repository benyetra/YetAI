# Editable Pipeline Schedules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins edit Celery beat cron times for the 7 PIPELINE_ENQUEUE_CATALOG orchestrators from the existing `/admin/pipelines` calendar UI, with changes taking effect within ~30 seconds without redeploying.

**Architecture:** Replace Celery's default `PersistentScheduler` with a custom `DatabaseScheduler` that overlays DB-backed overrides on top of the hardcoded `beat_schedule`. If a `pipeline_schedules` row exists for a task, it wins; if not, the hardcoded default applies. Beat re-reads the DB every 30 seconds. The frontend gains an edit modal on each calendar row.

**Tech Stack:** Celery 5.x beat scheduler subclass, SQLAlchemy, Alembic, FastAPI, React/Next.js.

---

## Key Design Decisions

1. **Editable set = 7 orchestrators in `PIPELINE_ENQUEUE_CATALOG`.** Live pollers (every 20s) and accuracy trackers stay hardcoded — not a UX win to expose them and the failure mode (admin sets poll to 5 hours) is bad.

2. **Override pattern, not replacement.** The `beat_schedule` dict in `celery_app.py` stays as the default. A new `pipeline_schedules` table stores admin overrides keyed by `task_name`. The custom scheduler loads defaults via `super().setup_schedule()` then layers DB overrides on top of those 7 entries. Result: empty DB = current behavior unchanged.

3. **Editable fields = `minute`, `hour`, `enabled`.** Day-of-week / day-of-month / month-of-year stay at `'*'` for v1. None of the existing 7 orchestrators use them.

4. **Reload cadence = 30s.** Set `Scheduler.sync_every = 30`. UX trade-off: admin clicks save, waits up to 30s for the change to take effect. Pub/sub-driven instant reload is a v2 consideration.

5. **Concurrency.** Celery beat runs as a single process (running two would double-fire tasks); the only contention is FastAPI writes vs. beat reads, which is standard SQLAlchemy.

6. **Reset path.** "Reset to default" deletes the override row. No "default schedule snapshot" stored — the source of truth for defaults is the Python config.

## File Structure

**Backend (new):**
- `app/models/database_models.py` — append `PipelineSchedule` model
- `alembic/versions/2026_05_23_pipeline_schedules.py` — migration adding `pipeline_schedules` table
- `app/core/db_scheduler.py` — `DatabaseScheduler` subclass of `PersistentScheduler`
- `app/services/pipeline_schedule_overrides.py` — read/write helpers for the new table

**Backend (modify):**
- `app/celery_app.py` — set `celery_app.conf.beat_scheduler = "app.core.db_scheduler.DatabaseScheduler"`
- `app/api/admin_pipelines.py` — add PATCH + reset endpoints
- `app/services/pipeline_schedule_service.py` — extend `serialize_schedule` to flag overridden entries

**Backend (tests):**
- `tests/test_pipeline_schedule_overrides.py` — DB helper unit tests
- `tests/test_db_scheduler.py` — scheduler overlay logic
- `tests/test_admin_pipeline_schedule_api.py` — PATCH/reset endpoints

**Frontend (new):**
- `frontend/src/components/admin/PipelineScheduleEditModal.tsx` — modal with hour/minute pickers + enable toggle + reset button

**Frontend (modify):**
- `frontend/src/lib/api/pipelines.ts` — add `updatePipelineSchedule`, `resetPipelineSchedule`
- `frontend/src/app/admin/pipelines/page.tsx` — enable edit buttons, render "Modified" badge

## Wire Format

The existing `GET /api/admin/pipelines/schedule` response gains two fields on each `scheduled[]` entry:

```json
{
  "is_overridden": false,
  "is_enabled": true
}
```

New endpoints:

- `PATCH /api/admin/pipelines/{task_name}/schedule`
  Body: `{ "hour": 3, "minute": 30, "enabled": true }`
  Behavior: upsert a `pipeline_schedules` row for `task_name`. Returns the updated row.
- `POST /api/admin/pipelines/{task_name}/schedule/reset`
  Behavior: delete the row if present. Returns `{ "reset": true }`.

Only the 7 task names in `PIPELINE_ENQUEUE_CATALOG` are accepted; anything else → 400.

---

## Tasks

### Task 1: PipelineSchedule model

**Files:**
- Modify: `backend/app/models/database_models.py` (append at end)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_schedule_overrides.py
from app.models.database_models import PipelineSchedule


def test_model_has_required_columns():
    cols = {c.name for c in PipelineSchedule.__table__.columns}
    assert cols == {
        "task_name", "minute", "hour", "enabled",
        "updated_at", "updated_by_user_id",
    }
    assert PipelineSchedule.__tablename__ == "pipeline_schedules"
```

- [ ] **Step 2: Run test to verify it fails**

```
../../.venv/bin/python -m pytest tests/test_pipeline_schedule_overrides.py::test_model_has_required_columns -v
```
Expected: ImportError on `PipelineSchedule`.

- [ ] **Step 3: Add the model**

Append to `backend/app/models/database_models.py`:

```python
class PipelineSchedule(Base):
    """Admin-editable override of a Celery beat schedule entry.

    Keyed by Celery task_name (must be in PIPELINE_ENQUEUE_CATALOG). When a
    row exists, the custom DatabaseScheduler uses these values instead of
    the hardcoded beat_schedule entry. Deleting the row reverts to default.
    """

    __tablename__ = "pipeline_schedules"

    task_name = Column(String(255), primary_key=True)
    minute = Column(Integer, nullable=False)
    hour = Column(Integer, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    updated_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
```

- [ ] **Step 4: Verify test passes**

```
../../.venv/bin/python -m pytest tests/test_pipeline_schedule_overrides.py::test_model_has_required_columns -v
```

- [ ] **Step 5: Commit (held until end of feature)**

---

### Task 2: Alembic migration

**Files:**
- Create: `backend/alembic/versions/2026_05_23_pipeline_schedules.py`

- [ ] **Step 1: Get current alembic head**

```
../../.venv/bin/python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('alembic.ini')).get_current_head())"
```
Expected: `2026_05_23_anf` (the admin_notifications migration from PR #11).

- [ ] **Step 2: Write the migration**

```python
"""pipeline schedule overrides

Adds pipeline_schedules table for admin-editable Celery beat schedule
overrides. Empty by default — schedules fall back to the hardcoded
beat_schedule entries.

Revision ID: 2026_05_23_psc
Revises: 2026_05_23_anf
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2026_05_23_psc"
down_revision: Union[str, Sequence[str], None] = "2026_05_23_anf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_schedules",
        sa.Column("task_name", sa.String(length=255), primary_key=True),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_table("pipeline_schedules")
```

- [ ] **Step 3: Verify it's the new head**

```
../../.venv/bin/python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; sd=ScriptDirectory.from_config(Config('alembic.ini')); print('head:', sd.get_current_head())"
```
Expected: `2026_05_23_psc`.

---

### Task 3: Override read/write service

**Files:**
- Create: `backend/app/services/pipeline_schedule_overrides.py`
- Test: `backend/tests/test_pipeline_schedule_overrides.py`

The service exposes pure read/write functions. We unit-test against an in-memory mock DB session.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline_schedule_overrides.py (additions)
from unittest.mock import MagicMock

from app.services import pipeline_schedule_overrides as ovr


def test_load_all_returns_dict_keyed_by_task_name():
    db = MagicMock()
    row = MagicMock(
        task_name="app.tasks.etl_pipeline.run_nba_update_pipeline",
        hour=3, minute=30, enabled=True,
    )
    db.query.return_value.all.return_value = [row]
    out = ovr.load_all(db)
    assert "app.tasks.etl_pipeline.run_nba_update_pipeline" in out
    assert out["app.tasks.etl_pipeline.run_nba_update_pipeline"].hour == 3


def test_upsert_rejects_unknown_task_name():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        ovr.upsert(
            MagicMock(),
            task_name="not.a.pipeline",
            hour=3, minute=30, enabled=True, user_id=1,
        )
    assert exc.value.status_code == 400


def test_upsert_validates_hour_minute_ranges():
    import pytest
    from fastapi import HTTPException

    name = "app.tasks.etl_pipeline.run_nba_update_pipeline"
    with pytest.raises(HTTPException):
        ovr.upsert(MagicMock(), task_name=name, hour=25, minute=0, enabled=True, user_id=1)
    with pytest.raises(HTTPException):
        ovr.upsert(MagicMock(), task_name=name, hour=3, minute=60, enabled=True, user_id=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: ImportError on `pipeline_schedule_overrides`.

- [ ] **Step 3: Implement service**

```python
# app/services/pipeline_schedule_overrides.py
"""Admin-editable Celery schedule overrides.

Read/write helpers for the pipeline_schedules table. The DatabaseScheduler
calls load_all() once per sync; the REST router calls upsert() and delete().
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.data.celery_tasks import PIPELINE_ENQUEUE_CATALOG
from app.models.database_models import PipelineSchedule

_EDITABLE: frozenset[str] = frozenset(
    e["task_name"] for e in PIPELINE_ENQUEUE_CATALOG
)


def is_editable(task_name: str) -> bool:
    return task_name in _EDITABLE


def load_all(db: Session) -> dict[str, PipelineSchedule]:
    rows = db.query(PipelineSchedule).all()
    return {r.task_name: r for r in rows}


def get(db: Session, task_name: str) -> Optional[PipelineSchedule]:
    return db.query(PipelineSchedule).filter_by(task_name=task_name).one_or_none()


def upsert(
    db: Session,
    *,
    task_name: str,
    hour: int,
    minute: int,
    enabled: bool,
    user_id: Optional[int],
) -> PipelineSchedule:
    if not is_editable(task_name):
        raise HTTPException(
            status_code=400,
            detail=f"task_name not in editable set: {task_name}",
        )
    if not 0 <= hour <= 23:
        raise HTTPException(status_code=400, detail="hour must be 0..23")
    if not 0 <= minute <= 59:
        raise HTTPException(status_code=400, detail="minute must be 0..59")

    row = db.query(PipelineSchedule).filter_by(task_name=task_name).one_or_none()
    if row is None:
        row = PipelineSchedule(task_name=task_name)
        db.add(row)
    row.hour = hour
    row.minute = minute
    row.enabled = enabled
    row.updated_by_user_id = user_id
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, task_name: str) -> bool:
    row = db.query(PipelineSchedule).filter_by(task_name=task_name).one_or_none()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
```

- [ ] **Step 4: Verify tests pass**

---

### Task 4: DatabaseScheduler subclass

**Files:**
- Create: `backend/app/core/db_scheduler.py`
- Test: `backend/tests/test_db_scheduler.py`

The scheduler subclass overlays DB rows onto the hardcoded schedule. Most of its logic is in `_apply_overrides`, which is pure and testable without booting Celery beat.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db_scheduler.py
from unittest.mock import MagicMock

from celery.schedules import crontab

from app.core.db_scheduler import apply_overrides
from app.models.database_models import PipelineSchedule


def test_apply_overrides_replaces_hour_minute_for_known_task():
    """Override row for an existing orchestrator updates its crontab."""
    NAME = "app.tasks.etl_pipeline.run_nba_update_pipeline"
    schedule_dict = {
        "nba-daily": {
            "task": NAME,
            "schedule": crontab(hour=3, minute=30),
        },
    }
    override = PipelineSchedule(task_name=NAME, hour=6, minute=15, enabled=True)
    out = apply_overrides(schedule_dict, {NAME: override})
    new_cron = out["nba-daily"]["schedule"]
    assert new_cron.hour == {6}
    assert new_cron.minute == {15}


def test_apply_overrides_removes_entry_when_disabled():
    """enabled=False means the task should not be in the active schedule."""
    NAME = "app.tasks.etl_pipeline.run_nba_update_pipeline"
    schedule_dict = {
        "nba-daily": {"task": NAME, "schedule": crontab(hour=3, minute=30)}
    }
    override = PipelineSchedule(task_name=NAME, hour=6, minute=15, enabled=False)
    out = apply_overrides(schedule_dict, {NAME: override})
    assert "nba-daily" not in out


def test_apply_overrides_ignores_overrides_for_unknown_tasks():
    """Orphan override row (e.g. task renamed) is silently skipped."""
    schedule_dict = {
        "nba-daily": {
            "task": "app.tasks.etl_pipeline.run_nba_update_pipeline",
            "schedule": crontab(hour=3, minute=30),
        }
    }
    override = PipelineSchedule(task_name="old.task.name", hour=6, minute=15, enabled=True)
    out = apply_overrides(schedule_dict, {"old.task.name": override})
    # Original unchanged, no new entry inserted.
    assert out == schedule_dict


def test_apply_overrides_leaves_non_orchestrator_entries_untouched():
    """Polling tasks etc. are never overridden — only PIPELINE_ENQUEUE_CATALOG entries."""
    schedule_dict = {
        "mlb-poll": {"task": "app.tasks.live_pollers.poll_mlb_live", "schedule": 20.0},
    }
    # Hypothetical attempt to override a non-orchestrator
    override = PipelineSchedule(
        task_name="app.tasks.live_pollers.poll_mlb_live",
        hour=6, minute=15, enabled=True,
    )
    out = apply_overrides(schedule_dict, {"app.tasks.live_pollers.poll_mlb_live": override})
    assert out["mlb-poll"]["schedule"] == 20.0
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: ImportError.

- [ ] **Step 3: Implement the scheduler**

```python
# app/core/db_scheduler.py
"""Custom Celery beat scheduler with admin-editable overrides.

Loads the hardcoded beat_schedule from celery_app.conf, then overlays any
rows present in pipeline_schedules (which is admin-managed). Polls the
DB every `sync_every` seconds for changes.
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

    Pure function — no Celery, no DB. Easy to unit-test.

    Rules:
      - Override applies only if task_name is in PIPELINE_ENQUEUE_CATALOG
        AND there's an entry in `schedule_dict` for that task_name.
      - enabled=False removes the entry (beat will not fire the task).
      - Unknown override task_names are silently ignored.
    """
    out = dict(schedule_dict)
    for key, entry in schedule_dict.items():
        task_name = entry.get("task")
        if task_name not in _ORCHESTRATOR_NAMES:
            continue
        override = overrides.get(task_name)
        if override is None:
            continue
        if not override.enabled:
            out.pop(key, None)
            continue
        new_entry = dict(entry)
        new_entry["schedule"] = crontab(hour=override.hour, minute=override.minute)
        out[key] = new_entry
    return out


class DatabaseScheduler(PersistentScheduler):
    """Celery beat scheduler that overlays pipeline_schedules rows on the
    hardcoded beat_schedule. Polls the DB every 30 seconds for changes.
    """

    # Override PersistentScheduler default (3 min) to a tighter window —
    # admin edits should take effect within ~30s.
    sync_every = 30

    # Keep a copy of the original hardcoded schedule. We re-apply overrides
    # against this on every sync rather than mutating in place, so disabling
    # an override (delete row) reverts cleanly.
    _hardcoded_schedule: dict[str, dict[str, Any]] = {}

    def setup_schedule(self) -> None:
        # Snapshot the hardcoded schedule before super applies it.
        self._hardcoded_schedule = deepcopy(dict(self.app.conf.beat_schedule))
        # Apply DB overrides into the conf schedule, then let super build
        # ScheduleEntry objects from the merged dict.
        merged = self._load_merged()
        self.app.conf.beat_schedule = merged
        super().setup_schedule()

    def sync(self) -> None:
        """Called every `sync_every` seconds. Re-merge and refresh entries."""
        try:
            merged = self._load_merged()
            self.app.conf.beat_schedule = merged
            self.merge_inplace(merged)
        except Exception:
            logger.exception("DatabaseScheduler.sync failed; keeping prior schedule")
        super().sync()

    def _load_merged(self) -> dict[str, dict[str, Any]]:
        """Return hardcoded ∪ DB overrides. Safe if DB unreachable."""
        try:
            with SessionLocal() as db:
                overrides = ovr.load_all(db)
        except Exception:
            logger.exception(
                "DatabaseScheduler could not load overrides; using hardcoded defaults"
            )
            overrides = {}
        return apply_overrides(self._hardcoded_schedule, overrides)
```

- [ ] **Step 4: Verify tests pass**

---

### Task 5: Wire scheduler in celery_app.py

**Files:**
- Modify: `backend/app/celery_app.py`

- [ ] **Step 1: Add config**

After the existing `celery_app.conf.update(...)` block:

```python
celery_app.conf.beat_scheduler = "app.core.db_scheduler.DatabaseScheduler"
```

- [ ] **Step 2: Verify import doesn't break**

```
../../.venv/bin/python -c "from app.celery_app import celery_app; from app.core.db_scheduler import DatabaseScheduler; print('ok')"
```

---

### Task 6: API endpoints (PATCH + reset)

**Files:**
- Modify: `backend/app/api/admin_pipelines.py`
- Test: `backend/tests/test_admin_pipeline_schedule_api.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_admin_pipeline_schedule_api.py
from unittest.mock import patch
from fastapi.testclient import TestClient

# (use existing pattern from other admin tests — dependency_overrides on require_admin)


def _admin_override():
    return {"id": 1, "user_id": 1, "is_admin": True}


def test_patch_rejects_unknown_task():
    import app.main as m
    m.app.dependency_overrides[m.require_admin] = _admin_override
    try:
        client = TestClient(m.app)
        r = client.patch(
            "/api/admin/pipelines/not.a.real.task/schedule",
            json={"hour": 3, "minute": 30, "enabled": True},
        )
        assert r.status_code == 400
    finally:
        m.app.dependency_overrides.clear()


# More tests: 200 path with successful upsert, reset endpoint, validation
```

- [ ] **Step 2: Add endpoints**

In `app/api/admin_pipelines.py`:

```python
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services import pipeline_schedule_overrides as ovr


class UpdateScheduleRequest(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    enabled: bool = True


@router.patch("/{task_name:path}/schedule")
async def update_schedule(
    task_name: str,
    payload: UpdateScheduleRequest,
    admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = ovr.upsert(
        db,
        task_name=task_name,
        hour=payload.hour,
        minute=payload.minute,
        enabled=payload.enabled,
        user_id=admin.get("id") or admin.get("user_id"),
    )
    return {
        "task_name": row.task_name,
        "hour": row.hour,
        "minute": row.minute,
        "enabled": row.enabled,
    }


@router.post("/{task_name:path}/schedule/reset")
async def reset_schedule(
    task_name: str,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not ovr.is_editable(task_name):
        raise HTTPException(status_code=400, detail=f"task_name not editable: {task_name}")
    deleted = ovr.delete(db, task_name)
    return {"reset": deleted}
```

Important: register these BEFORE the existing `/schedule` GET, OR use `:path` converter to disambiguate. Actually since the new routes are `/{task_name:path}/schedule[/reset]`, FastAPI's order matters — the existing `/schedule` (literal) must be declared first OR the new routes will match it. Verify with a curl after wiring.

- [ ] **Step 3: Extend serialize_schedule to include is_overridden/is_enabled**

In `app/services/pipeline_schedule_service.py`:
- Accept an optional `overrides: dict[str, Any] = None` parameter
- When serializing each scheduled entry, set `is_overridden = task_name in overrides` and `is_enabled` (True unless overridden to disabled)

And in `app/api/admin_pipelines.py:get_schedule`, load overrides from DB before serializing.

- [ ] **Step 4: Verify tests pass**

---

### Task 7: Frontend API client extensions

**Files:**
- Modify: `frontend/src/lib/api/pipelines.ts`

- [ ] **Step 1: Add client methods**

```typescript
export interface UpdateScheduleRequest {
  hour: number;
  minute: number;
  enabled: boolean;
}

export async function updatePipelineSchedule(
  taskName: string,
  body: UpdateScheduleRequest,
): Promise<{ task_name: string; hour: number; minute: number; enabled: boolean }> {
  const res = await apiRequest(`/api/admin/pipelines/${encodeURIComponent(taskName)}/schedule`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Update failed (${res.status}): ${await res.text()}`);
  return res.json();
}

export async function resetPipelineSchedule(taskName: string): Promise<{ reset: boolean }> {
  const res = await apiRequest(
    `/api/admin/pipelines/${encodeURIComponent(taskName)}/schedule/reset`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error(`Reset failed (${res.status}): ${await res.text()}`);
  return res.json();
}
```

Also extend the `ScheduledEntry` type with optional `is_overridden?: boolean` and `is_enabled?: boolean`.

---

### Task 8: Edit modal component

**Files:**
- Create: `frontend/src/components/admin/PipelineScheduleEditModal.tsx`

Self-contained modal with hour picker (0–23 select), minute picker (0–59 select; or constrained to /5 multiples for UX), enabled checkbox, Save / Reset to default / Cancel buttons.

```tsx
'use client';

import { useState } from 'react';
import { X, RotateCcw } from 'lucide-react';
import {
  updatePipelineSchedule,
  resetPipelineSchedule,
  type ScheduledEntry,
} from '@/lib/api/pipelines';

interface Props {
  entry: ScheduledEntry;
  onClose: () => void;
  onSaved: () => void;
}

export function PipelineScheduleEditModal({ entry, onClose, onSaved }: Props) {
  // Initial values: prefer the entry's current crontab. minute/hour come from
  // arrays in the wire format; we only support single values here.
  const initialHour = Array.isArray(entry.crontab.hour) ? entry.crontab.hour[0] ?? 0 : 0;
  const initialMinute = Array.isArray(entry.crontab.minute) ? entry.crontab.minute[0] ?? 0 : 0;

  const [hour, setHour] = useState(initialHour);
  const [minute, setMinute] = useState(initialMinute);
  const [enabled, setEnabled] = useState(entry.is_enabled !== false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleSave = async () => {
    setBusy(true);
    setErr(null);
    try {
      await updatePipelineSchedule(entry.task_name, { hour, minute, enabled });
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleReset = async () => {
    if (!confirm(`Reset ${entry.label} to default?`)) return;
    setBusy(true);
    setErr(null);
    try {
      await resetPipelineSchedule(entry.task_name);
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
      <div className="bg-zinc-950 border border-zinc-800 rounded-lg w-full max-w-md text-zinc-100">
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <h3 className="text-sm font-medium">{entry.label}</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-4 space-y-4">
          <div className="text-xs text-zinc-500 font-mono">{entry.task_name}</div>
          <div className="flex items-center gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-zinc-400">Hour (ET)</label>
              <select
                value={hour}
                onChange={e => setHour(Number(e.target.value))}
                className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm"
              >
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>{h.toString().padStart(2, '0')}</option>
                ))}
              </select>
            </div>
            <div className="text-zinc-500 mt-5">:</div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-zinc-400">Minute</label>
              <select
                value={minute}
                onChange={e => setMinute(Number(e.target.value))}
                className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm"
              >
                {Array.from({ length: 60 }, (_, m) => (
                  <option key={m} value={m}>{m.toString().padStart(2, '0')}</option>
                ))}
              </select>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={e => setEnabled(e.target.checked)}
            />
            Enabled
          </label>
          {err && <div className="text-xs text-red-400">{err}</div>}
          <div className="text-[11px] text-zinc-500">
            Changes take effect within ~30 seconds (next beat sync).
          </div>
        </div>
        <div className="flex items-center justify-between gap-2 p-4 border-t border-zinc-800">
          <button
            onClick={handleReset}
            disabled={busy || !entry.is_overridden}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-30"
            title={entry.is_overridden ? 'Reset to hardcoded default' : 'No override to reset'}
          >
            <RotateCcw className="w-3 h-3" />
            Reset to default
          </button>
          <div className="flex gap-2">
            <button onClick={onClose} disabled={busy} className="px-3 py-1.5 text-sm border border-zinc-700 rounded">
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={busy}
              className="px-3 py-1.5 text-sm bg-purple-600 hover:bg-purple-700 rounded disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

---

### Task 9: Wire modal into the calendar page

**Files:**
- Modify: `frontend/src/app/admin/pipelines/page.tsx`

- [ ] Replace the disabled `<button>Edit</button>` with a button that opens the modal for that entry. Track `editing: ScheduledEntry | null` in page state.
- [ ] Add "Modified" badge next to the cadence text when `entry.is_overridden`.
- [ ] On save/reset, call `reload()` to refresh.
- [ ] Only show edit button when `entry.is_orchestrator` is true (other crontab entries stay non-editable in v1).

---

### Task 10: Verify, format, commit

- [ ] `cd backend && ../../.venv/bin/black --check .` — should be clean
- [ ] `cd backend && ../../.venv/bin/python -m pytest tests/test_pipeline_schedule_overrides.py tests/test_db_scheduler.py tests/test_admin_pipeline_schedule_api.py tests/test_pipeline_schedule_service.py` — all green
- [ ] `cd frontend && npx tsc --noEmit` — same baseline error count as main
- [ ] `cd backend && ../../.venv/bin/python -c "import app.main"` — boots cleanly with new scheduler config
- [ ] Single commit, push, open PR

---

## Risks & Mitigations

1. **Custom scheduler crashes beat process.** If `DatabaseScheduler.setup_schedule` raises, no tasks fire. Mitigation: `_load_merged` wraps DB access in try/except and falls back to the hardcoded snapshot. Worst case: DB unreachable → behave exactly like hardcoded.

2. **A renamed orchestrator leaves an orphan override row.** `apply_overrides` tested to ignore orphans. UI doesn't surface them. Could add a cleanup endpoint in v2.

3. **Beat process needs to be restarted for `beat_scheduler` config change to take effect.** Document this in the PR description — the Railway deploy will roll the worker.

4. **Two beat processes (misconfiguration) double-fire.** Outside this PR's scope; standard Celery operational concern.
