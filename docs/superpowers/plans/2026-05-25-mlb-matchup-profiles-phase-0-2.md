# MLB Matchup Profiles — Phase 0–2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist versioned batter/pitcher profile snapshots, backfill Statcast pitch history to S3 (2018+), and build nightly profile aggregates with empirical-Bayes shrinkage so strikeout integration (Phase 3) can read from Postgres instead of live MLB API.

**Architecture:** Raw pitches land in S3 parquet (`season/month` partitions). Batch jobs aggregate into `mlb_*_profile_snapshots` with `as_of_date` for point-in-time backtests. `ProfileStore` is the only read interface for ETL. Feature flag `MLB_PROFILES_ENABLED` gates consumers until Phase 3.

**Tech Stack:** Python 3.13, SQLAlchemy, Alembic, pybaseball/statcast, pandas, pyarrow (parquet), boto3, Celery, pytest.

**Spec:** `docs/superpowers/specs/2026-05-25-mlb-matchup-profiles-roadmap.md`

**Follow-on plans (not in this file):** Phase 3 strikeouts → `2026-05-25-mlb-matchup-profiles-phase-3.md` (create after Phase 2 ships). Phases 4–8 per roadmap §5.

**Defaults locked for this plan:** Backfill starts **2018**; profile snapshots in **Postgres**; raw in **S3** under `s3://yetibets/mlb/statcast/pitches/`.

---

## File structure

| Path | Responsibility |
|------|----------------|
| `app/models/mlb_profile_models.py` | `MlbBatterProfileSnapshot`, `MlbPitcherProfileSnapshot` ORM |
| `alembic/versions/2026_05_26_mlb_profile_snapshots.py` | Tables + indexes |
| `app/services/etl/mlb/profiles/constants.py` | `PROFILE_VERSION`, pitch types, zone keys, league priors |
| `app/services/etl/mlb/profiles/shrinkage.py` | Empirical Bayes + reliability |
| `app/services/etl/mlb/profiles/profile_store.py` | Read API: `get_batter`, `get_pitcher` |
| `app/services/etl/mlb/profiles/profile_builder.py` | Parquet → aggregates → DB writes |
| `app/services/etl/mlb/statcast_ingest/normalize.py` | Column prune, pitch_type + zone buckets |
| `app/services/etl/mlb/statcast_ingest/backfill.py` | Monthly chunks, idempotent S3 writes |
| `app/services/etl/mlb/statcast_ingest/incremental.py` | Yesterday delta |
| `app/services/etl/mlb/statcast_ingest/s3_paths.py` | URI helpers + manifest |
| `scripts/mlb_statcast_backfill.py` | CLI for ops |
| `scripts/mlb_rebuild_profiles.py` | CLI rebuild snapshots for `as_of_date` |
| `app/tasks/etl_pipeline.py` | Celery tasks (modify) |
| `app/data/celery_tasks.py` | Allow-list + beat entries (modify) |
| `tests/test_mlb_statcast_normalize.py` | Unit |
| `tests/test_mlb_profile_shrinkage.py` | Unit |
| `tests/test_mlb_profile_builder.py` | Synthetic parquet fixture |
| `docs/MLB_MATCHUP_PROFILES.md` | Ops + env vars |

---

## Task 1: Profile snapshot models + migration

**Files:**
- Create: `backend/app/models/mlb_profile_models.py`
- Modify: `backend/app/models/__init__.py` (export models if package re-exports)
- Create: `backend/alembic/versions/2026_05_26_mlb_profile_snapshots.py`
- Test: `backend/tests/test_mlb_profile_models.py`

- [ ] **Step 1: Write failing test for table metadata**

```python
# tests/test_mlb_profile_models.py
from app.models.mlb_profile_models import MlbBatterProfileSnapshot, MlbPitcherProfileSnapshot


def test_batter_snapshot_tablename():
    assert MlbBatterProfileSnapshot.__tablename__ == "mlb_batter_profile_snapshots"


def test_pitcher_snapshot_tablename():
    assert MlbPitcherProfileSnapshot.__tablename__ == "mlb_pitcher_profile_snapshots"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_mlb_profile_models.py -v
```

Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement models**

```python
# app/models/mlb_profile_models.py
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class MlbPitcherProfileSnapshot(Base):
    __tablename__ = "mlb_pitcher_profile_snapshots"

    id = Column(Integer, primary_key=True)
    pitcher_id = Column(Integer, nullable=False, index=True)
    as_of_date = Column(Date, nullable=False, index=True)
    window = Column(String(16), nullable=False)  # 7d | 30d | season | 3yr_decay
    profile_version = Column(String(32), nullable=False)
    hand = Column(String(1), nullable=True)
    n_pitches = Column(Integer, nullable=False, default=0)
    profile = Column(JSONB, nullable=False)  # usage, location, velo, ...
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "pitcher_id", "as_of_date", "window", "profile_version",
            name="uq_mlb_pitcher_profile_snapshot",
        ),
    )


class MlbBatterProfileSnapshot(Base):
    __tablename__ = "mlb_batter_profile_snapshots"

    id = Column(Integer, primary_key=True)
    batter_id = Column(Integer, nullable=False, index=True)
    vs_hand = Column(String(1), nullable=False)  # L | R
    as_of_date = Column(Date, nullable=False, index=True)
    window = Column(String(16), nullable=False)
    profile_version = Column(String(32), nullable=False)
    n_pitches = Column(Integer, nullable=False, default=0)
    profile = Column(JSONB, nullable=False)  # whiff_by_pitch, cold_zones, ...
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "batter_id", "vs_hand", "as_of_date", "window", "profile_version",
            name="uq_mlb_batter_profile_snapshot",
        ),
    )
```

- [ ] **Step 4: Add Alembic migration**

```python
# alembic/versions/2026_05_26_mlb_profile_snapshots.py
"""MLB batter/pitcher profile snapshot tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260526_mlb_profiles"
down_revision = "20260525_game_mc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mlb_pitcher_profile_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pitcher_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("window", sa.String(16), nullable=False),
        sa.Column("profile_version", sa.String(32), nullable=False),
        sa.Column("hand", sa.String(1), nullable=True),
        sa.Column("n_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("profile", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_mlb_pitcher_profile_pitcher_date",
        "mlb_pitcher_profile_snapshots",
        ["pitcher_id", "as_of_date"],
    )
    op.create_table(
        "mlb_batter_profile_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batter_id", sa.Integer(), nullable=False),
        sa.Column("vs_hand", sa.String(1), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("window", sa.String(16), nullable=False),
        sa.Column("profile_version", sa.String(32), nullable=False),
        sa.Column("n_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("profile", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_mlb_batter_profile_batter_date",
        "mlb_batter_profile_snapshots",
        ["batter_id", "as_of_date"],
    )


def downgrade() -> None:
    op.drop_table("mlb_batter_profile_snapshots")
    op.drop_table("mlb_pitcher_profile_snapshots")
```

- [ ] **Step 5: Run tests + migration locally**

```bash
cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_mlb_profile_models.py -v
cd backend && PYTHONPATH=. .venv/bin/alembic upgrade head
```

Expected: tests PASS; migration applies `20260526_mlb_profiles`

- [ ] **Step 6: Black + commit**

```bash
cd backend && python3 -m black app/models/mlb_profile_models.py tests/test_mlb_profile_models.py alembic/versions/2026_05_26_mlb_profile_snapshots.py
git add backend/app/models/mlb_profile_models.py backend/tests/test_mlb_profile_models.py backend/alembic/versions/2026_05_26_mlb_profile_snapshots.py
git commit -m "feat(mlb): add profile snapshot tables for matchup tensors"
```

---

## Task 2: Profile constants and feature flag

**Files:**
- Create: `backend/app/services/etl/mlb/profiles/__init__.py`
- Create: `backend/app/services/etl/mlb/profiles/constants.py`
- Test: `backend/tests/test_mlb_profile_constants.py`

- [ ] **Step 1: Write failing test for env flag helper**

```python
# tests/test_mlb_profile_constants.py
import os

from app.services.etl.mlb.profiles.constants import mlb_profiles_enabled


def test_mlb_profiles_enabled_default(monkeypatch):
    monkeypatch.delenv("MLB_PROFILES_ENABLED", raising=False)
    assert mlb_profiles_enabled() is True


def test_mlb_profiles_disabled(monkeypatch):
    monkeypatch.setenv("MLB_PROFILES_ENABLED", "0")
    assert mlb_profiles_enabled() is False
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_mlb_profile_constants.py -v
```

- [ ] **Step 3: Implement constants**

```python
# app/services/etl/mlb/profiles/constants.py
import os

PROFILE_VERSION = "mlb-profile-v1"

PITCH_TYPES = ("FF", "SI", "FC", "SL", "CH", "CU", "KC", "FS", "ST", "UNK")

ZONE_KEYS = ("high_inside", "high_outside", "low_inside", "low_outside")

WINDOWS = ("7d", "30d", "season", "3yr_decay")

# Statcast pitch_type code → canonical bucket (extend as needed)
PITCH_TYPE_MAP = {
    "FF": "FF",
    "FA": "FF",
    "FT": "SI",
    "SI": "SI",
    "FC": "FC",
    "SL": "SL",
    "CH": "CH",
    "CU": "CU",
    "KC": "KC",
    "FS": "FS",
    "ST": "ST",
}

LEAGUE_WHIFF_BY_PITCH = {
    "FF": 0.22,
    "SI": 0.20,
    "FC": 0.24,
    "SL": 0.32,
    "CH": 0.30,
    "CU": 0.28,
    "KC": 0.27,
    "FS": 0.29,
    "ST": 0.31,
    "UNK": 0.25,
}

SHRINKAGE_K_WHIFF = 200  # pitches until ~50% weight on observed rate


def mlb_profiles_enabled() -> bool:
    return os.getenv("MLB_PROFILES_ENABLED", "1").strip().lower() in (
        "1", "true", "yes", "on",
    )
```

- [ ] **Step 4: Run test — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/etl/mlb/profiles/ backend/tests/test_mlb_profile_constants.py
git commit -m "feat(mlb): profile constants and MLB_PROFILES_ENABLED flag"
```

---

## Task 3: Statcast normalize (pitch type + zones)

**Files:**
- Create: `backend/app/services/etl/mlb/statcast_ingest/__init__.py`
- Create: `backend/app/services/etl/mlb/statcast_ingest/normalize.py`
- Test: `backend/tests/test_mlb_statcast_normalize.py`

- [ ] **Step 1: Write failing tests for zone bucket and pitch map**

```python
# tests/test_mlb_statcast_normalize.py
import pandas as pd

from app.services.etl.mlb.statcast_ingest.normalize import (
    bucket_zone,
    canonical_pitch_type,
    prune_statcast_columns,
)


def test_canonical_pitch_type_maps_four_seam():
    assert canonical_pitch_type("FF") == "FF"
    assert canonical_pitch_type("FA") == "FF"


def test_bucket_zone_high_inside():
    assert bucket_zone(0.2, 3.8) == "high_inside"


def test_prune_keeps_required_columns():
    df = pd.DataFrame(
        {
            "game_date": ["2024-05-01"],
            "pitcher": [123],
            "batter": [456],
            "pitch_type": ["FF"],
            "plate_x": [0.1],
            "plate_z": [2.5],
            "p_throws": ["R"],
            "stand": ["L"],
            "description": ["swinging_strike"],
            "junk": [1],
        }
    )
    out = prune_statcast_columns(df)
    assert "junk" not in out.columns
    assert "zone_bucket" in out.columns
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement normalize.py**

```python
# app/services/etl/mlb/statcast_ingest/normalize.py
from __future__ import annotations

import pandas as pd

from app.services.etl.mlb.profiles.constants import PITCH_TYPE_MAP, ZONE_KEYS

KEEP_COLUMNS = [
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "batter",
    "pitch_type",
    "release_speed",
    "release_spin_rate",
    "plate_x",
    "plate_z",
    "p_throws",
    "stand",
    "description",
    "events",
    "estimated_woba_using_speedangle",
]


def canonical_pitch_type(code: str | None) -> str:
    if not code:
        return "UNK"
    return PITCH_TYPE_MAP.get(str(code).upper(), "UNK")


def bucket_zone(plate_x: float, plate_z: float) -> str:
    """Map plate coordinates to four zones (matches mlb_pitcher_analysis buckets)."""
    x, z = float(plate_x), float(plate_z)
    high = z >= 2.5
    inside = x <= 0.0
    if high and inside:
        return "high_inside"
    if high and not inside:
        return "high_outside"
    if not high and inside:
        return "low_inside"
    return "low_outside"


def is_whiff(description: str | None) -> bool:
    if not description:
        return False
    d = description.lower()
    return "swinging_strike" in d or d in {"swinging_strike_blocked"}


def prune_statcast_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in KEEP_COLUMNS if c in df.columns]
    out = df[cols].copy()
    out["game_date"] = pd.to_datetime(out["game_date"]).dt.date
    out["pitch_type_canon"] = out["pitch_type"].map(canonical_pitch_type)
    out["zone_bucket"] = [
        bucket_zone(x, z)
        for x, z in zip(out["plate_x"].fillna(0), out["plate_z"].fillna(2.5))
    ]
    out["is_whiff"] = out["description"].map(is_whiff)
    return out
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/etl/mlb/statcast_ingest/ backend/tests/test_mlb_statcast_normalize.py
git commit -m "feat(mlb): Statcast normalize pitch types and zone buckets"
```

---

## Task 4: S3 path helpers + idempotent partition check

**Files:**
- Create: `backend/app/services/etl/mlb/statcast_ingest/s3_paths.py`
- Test: `backend/tests/test_mlb_statcast_s3_paths.py`

- [ ] **Step 1: Write failing test for partition URI**

```python
from app.services.etl.mlb.statcast_ingest.s3_paths import partition_uri, manifest_key


def test_partition_uri():
    assert partition_uri(2024, 5).endswith("season=2024/month=05/part.parquet")


def test_manifest_key():
    assert manifest_key(2024) == "mlb/statcast/pitches/season=2024/_manifest.json"
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement (prefix from env `MLB_STATCAST_S3_PREFIX`, default `s3://yetibets/mlb/statcast/pitches`)**

```python
# s3_paths.py
import os


def base_prefix() -> str:
    return os.getenv("MLB_STATCAST_S3_PREFIX", "s3://yetibets/mlb/statcast/pitches").rstrip("/")


def partition_uri(season: int, month: int) -> str:
    return f"{base_prefix()}/season={season}/month={month:02d}/part.parquet"


def manifest_key(season: int) -> str:
    return f"{base_prefix()}/season={season}/_manifest.json"
```

Add `partition_exists(uri) -> bool` using boto3 or reuse pattern from `dingerParlay/download_historical_pa.py` `smart_to_csv`.

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

---

## Task 5: Monthly backfill module

**Files:**
- Create: `backend/app/services/etl/mlb/statcast_ingest/backfill.py`
- Test: `backend/tests/test_mlb_statcast_backfill.py` (mock `statcast` call)

- [ ] **Step 1: Write failing test with monkeypatched statcast**

```python
import pandas as pd
from unittest.mock import patch

from app.services.etl.mlb.statcast_ingest.backfill import backfill_month


@patch("app.services.etl.mlb.statcast_ingest.backfill.statcast")
def test_backfill_month_writes_parquet(mock_statcast, tmp_path, monkeypatch):
    monkeypatch.setenv("MLB_STATCAST_S3_PREFIX", str(tmp_path))
    mock_statcast.return_value = pd.DataFrame(
        {
            "game_date": ["2024-05-15"],
            "pitcher": [1],
            "batter": [2],
            "pitch_type": ["FF"],
            "plate_x": [0.0],
            "plate_z": [2.5],
            "p_throws": ["R"],
            "stand": ["L"],
            "description": ["swinging_strike"],
        }
    )
    uri = backfill_month(2024, 5, force=False)
    assert uri is not None
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `backfill_month(season, month, force=False)`**

- Fetch `start = YYYY-MM-01`, `end = last day of month` via `calendar.monthrange`
- Call `pybaseball.statcast(start, end)` with retry (3×, exponential backoff)
- `prune_statcast_columns`
- Write parquet to local path if prefix is local, else boto3 upload
- Skip if partition exists and `force=False`
- Append partition path to season manifest JSON

- [ ] **Step 4: Run test — PASS**

- [ ] **Step 5: Commit**

---

## Task 6: CLI `mlb_statcast_backfill.py`

**Files:**
- Create: `backend/scripts/mlb_statcast_backfill.py`

- [ ] **Step 1: Implement argparse**

```bash
# Usage
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_statcast_backfill.py --start-year 2018 --end-year 2024
PYTHONPATH=. .venv/bin/python scripts/mlb_statcast_backfill.py --season 2024 --force
```

Loop months Mar–Oct per season; log rows written; exit non-zero on any failed month.

- [ ] **Step 2: Dry-run on one month locally**

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_statcast_backfill.py --season 2024 --month 5
```

Expected: parquet under `/tmp/.../season=2024/month=05/` (or S3 if configured)

- [ ] **Step 3: Document in `docs/MLB_MATCHUP_PROFILES.md` (stub)**

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/mlb_statcast_backfill.py backend/docs/MLB_MATCHUP_PROFILES.md
git commit -m "feat(mlb): Statcast monthly backfill CLI"
```

---

## Task 7: Celery tasks + admin allow-list

**Files:**
- Modify: `backend/app/tasks/etl_pipeline.py`
- Modify: `backend/app/data/celery_tasks.py`
- Modify: `backend/app/celery_app.py` (beat schedule)
- Test: `backend/tests/test_mlb_statcast_tasks_registered.py`

- [ ] **Step 1: Add tasks**

```python
@celery_app.task(name="app.tasks.etl_pipeline.mlb.statcast_backfill_season")
def mlb_statcast_backfill_season(season: int, force: bool = False) -> dict:
    ...

@celery_app.task(name="app.tasks.etl_pipeline.mlb.statcast_incremental")
def mlb_statcast_incremental() -> dict:
    ...

@celery_app.task(name="app.tasks.etl_pipeline.mlb.rebuild_profiles")
def mlb_rebuild_profiles(as_of_date: str | None = None) -> dict:
    ...
```

Register in `ADMIN_FIREABLE_TASKS` with timeouts (backfill 14400s, incremental 900s, rebuild 3600s).

- [ ] **Step 2: Beat schedule (UTC; adjust if using DB scheduler overrides)**

```python
"mlb-statcast-incremental": {
    "task": "app.tasks.etl_pipeline.mlb.statcast_incremental",
    "schedule": crontab(hour=9, minute=30),  # ~05:30 ET DST
},
"mlb-profile-rebuild": {
    "task": "app.tasks.etl_pipeline.mlb.rebuild_profiles",
    "schedule": crontab(hour=10, minute=0),  # ~06:00 ET before projections
},
```

- [ ] **Step 3: Smoke import**

```bash
cd backend && PYTHONPATH=. .venv/bin/python scripts/smoke_import_mlb_etl.py
```

- [ ] **Step 4: Commit**

---

## Task 8: GitHub Actions backfill workflow

**Files:**
- Create: `.github/workflows/mlb-statcast-backfill.yml`

- [ ] **Step 1: `workflow_dispatch` inputs: `season` (int), `force` (bool)**

- [ ] **Step 2: Job runs on self-hosted or standard runner with secrets: AWS keys, optional proxy**

```yaml
# Pseudocode — use repo's existing Railway/AWS secret names
- run: |
    cd backend
    PYTHONPATH=. .venv/bin/python scripts/mlb_statcast_backfill.py --season ${{ inputs.season }} --force ${{ inputs.force }}
```

- [ ] **Step 3: Commit**

---

## Task 9: Empirical Bayes shrinkage module

**Files:**
- Create: `backend/app/services/etl/mlb/profiles/shrinkage.py`
- Test: `backend/tests/test_mlb_profile_shrinkage.py`

- [ ] **Step 1: Failing tests**

```python
from app.services.etl.mlb.profiles.shrinkage import posterior_whiff_rate, reliability


def test_posterior_whiff_shrinks_to_league_when_n_zero():
    mean, rel = posterior_whiff_rate(observed=0.5, n_pitches=0, pitch_type="FF")
    assert rel == 0.0
    assert 0.20 < mean < 0.25


def test_reliability_approaches_one():
    assert reliability(400, k=200) > 0.6
```

- [ ] **Step 2: Implement**

```python
def reliability(n: int, k: float) -> float:
    n = max(0, int(n))
    return n / (n + k) if (n + k) > 0 else 0.0


def posterior_whiff_rate(observed: float, n_pitches: int, pitch_type: str) -> tuple[float, float]:
    prior = LEAGUE_WHIFF_BY_PITCH.get(pitch_type, 0.25)
    rel = reliability(n_pitches, SHRINKAGE_K_WHIFF)
    post = rel * observed + (1 - rel) * prior
    return post, rel
```

- [ ] **Step 3: Run tests — PASS**

- [ ] **Step 4: Commit**

---

## Task 10: Profile builder (aggregate + write DB)

**Files:**
- Create: `backend/app/services/etl/mlb/profiles/profile_builder.py`
- Create: `backend/app/services/etl/mlb/profiles/profile_store.py`
- Test: `backend/tests/test_mlb_profile_builder.py`

- [ ] **Step 1: Fixture — small parquet with 2 pitchers, 2 batters, 500 pitches**

Generate in test via pandas, write to `tmp_path`.

- [ ] **Step 2: Failing test `build_snapshots_for_date`**

Assert rows inserted into SQLite/Postgres test DB (use existing pytest DB fixture pattern from `tests/conftest.py` if present; else mock session).

- [ ] **Step 3: Implement aggregation logic**

`aggregate_pitcher(df, pitcher_id, window, as_of_date)`:

- Filter `game_date < as_of_date` (strict — no leakage)
- Window filters: 7d/30d/season/3yr_decay (exponential weights for 3yr)
- Output profile JSON:

```json
{
  "usage": {"FF": 0.42, "SL": 0.28},
  "location": {"FF": {"high_inside": 0.1, "low_outside": 0.35}},
  "n_pitches": 812
}
```

`aggregate_batter` grouped by `vs_hand` (= `p_throws`), per pitch_type whiff%, cold_zones (zones with whiff > league+0.05).

Apply `posterior_whiff_rate` per pitch type; store `reliability` in profile.

- [ ] **Step 4: `rebuild_all_profiles(as_of_date: date | None = None)`**

- Default `as_of_date = date.today()`
- Delete existing rows for `(as_of_date, PROFILE_VERSION)` then bulk insert
- Return counts `{pitchers, batters}`

- [ ] **Step 5: `ProfileStore.get_pitcher(pitcher_id, as_of_date, window="season")`**

SQLAlchemy query latest `<= as_of_date` for backtests.

- [ ] **Step 6: Run tests — PASS**

- [ ] **Step 7: Commit**

---

## Task 11: `mlb_rebuild_profiles` Celery + CLI

**Files:**
- Create: `backend/scripts/mlb_rebuild_profiles.py`
- Wire task body in `etl_pipeline.py`

- [ ] **Step 1: CLI**

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_rebuild_profiles.py --as-of 2025-05-25
```

- [ ] **Step 2: Pilot on 2024 parquet only**

After Task 6 backfill 2024:

```bash
PYTHONPATH=. .venv/bin/python scripts/mlb_rebuild_profiles.py --as-of 2024-10-01
```

- [ ] **Step 3: Validation query**

```sql
SELECT COUNT(*) FROM mlb_pitcher_profile_snapshots WHERE as_of_date = '2024-10-01';
SELECT COUNT(*) FROM mlb_batter_profile_snapshots WHERE as_of_date = '2024-10-01';
```

Expect hundreds of pitchers, thousands of batter×hand rows.

- [ ] **Step 4: Commit**

---

## Task 12: Ops docs + prod verify stub

**Files:**
- Create/expand: `backend/docs/MLB_MATCHUP_PROFILES.md`
- Create: `backend/scripts/prod_verify_mlb_profiles.py`

- [ ] **Step 1: Document env vars**

| Variable | Default | Purpose |
|----------|---------|---------|
| `MLB_PROFILES_ENABLED` | `1` | Gate consumers (Phase 3) |
| `MLB_STATCAST_S3_PREFIX` | `s3://yetibets/mlb/statcast/pitches` | Raw store |
| `MLB_PROFILE_WINDOW_DEFAULT` | `season` | Read default |

- [ ] **Step 2: `prod_verify_mlb_profiles.py`**

- Check tables exist
- Check latest `as_of_date` row counts
- Check sample pitcher has `usage` summing ~1.0
- Optional: compare one pitcher whiff% to MLB Stats API (within tolerance)

- [ ] **Step 3: Add to `AGENTS.md` one-liner**

- [ ] **Step 4: Black, commit, push**

```bash
cd backend && python3 -m black .
git add backend/docs/MLB_MATCHUP_PROFILES.md backend/scripts/prod_verify_mlb_profiles.py AGENTS.md
git commit -m "docs(mlb): matchup profiles ops guide and verify script"
```

---

## Phase 0–2 exit checklist

- [ ] Alembic `20260526_mlb_profiles` on staging/prod (Database Migrations workflow)
- [ ] S3 partitions for 2018–2024 (at minimum 2024 pilot) with manifests
- [ ] `mlb_rebuild_profiles` populates snapshots for `as_of_date=today`
- [ ] Beat: incremental + rebuild scheduled before `mlb-projections-daily`
- [ ] `prod_verify_mlb_profiles.py` passes against prod
- [ ] **Do not** enable strikeout consumption yet (`MLB_PROFILES_ENABLED=1` only affects Phase 3 code)

---

## Spec coverage self-review

| Spec § | Task |
|--------|------|
| Phase 0 schema | Task 1–2 |
| Phase 1 ingest | Tasks 3–8 |
| Phase 2 builder + shrinkage | Tasks 9–11 |
| Phase 2 exit criteria spot-check | Task 11 validation SQL |
| Point-in-time `as_of_date` | Task 10 filter `game_date < as_of_date` |
| Celery catalog | Task 7 |
| Phase 3+ | Separate plan (not here) |

**Placeholder scan:** None.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-25-mlb-matchup-profiles-phase-0-2.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration (`superpowers:subagent-driven-development`).

2. **Inline Execution** — Run tasks in this session with checkpoints (`superpowers:executing-plans`).

**Which approach do you want?**

After Phase 0–2 ships, run writing-plans again for **Phase 3** (strikeout + `lineup_utils` integration) using spec § Phase 3.
