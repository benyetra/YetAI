# YetiBets → YetAI ETL migration status

Living document while Railway deploys are paused (post-outage). Update after each local verification batch and after production runs.

**Reference (read-only):** `YetiBets/`  
**Target:** `YetAI/YetAI/backend/` — Celery on `celery-worker`, Beat schedules in `app/celery_app.py`

---

## Last updated

| Field | Value |
|-------|--------|
| Date | 2026-05-20 |
| `main` tip | `dc1b56ba` (admin enqueue API + enqueue script) |
| Railway | API up; **deploys paused**; Redis was timing out — re-verify before prod run |
| Local tooling | Import smoke + NBA totals unit tests + expanded validators (this session) |

---

## Sport pipelines

### MLB — code complete, prod not verified

| Area | Status |
|------|--------|
| Celery orchestration | `run_mlb_update_pipeline`, `run_mlb_store_actuals` wired |
| Module port | ~40+ modules under `app/services/etl/mlb/` (see `MLB_ETL_PARITY.md`) |
| Import layout fixes | `5cf24812` (package imports for `mlb_pitcher_analysis`, etc.) |
| Execution order | strikeouts → hits → persist → weather/blowouts (fixed vs old GHA) |
| **Production run** | **Not confirmed** after import fixes (Redis/outage blocked enqueue) |
| Not on Beat | `mlb_ev`, HR ML (needs S3 env), backtest/retrain CLIs |

**Local checks (no deploy):**

```bash
cd backend
PYTHONPATH=. python scripts/smoke_import_mlb_etl.py
PYTHONPATH=. python scripts/validate_mlb_pipeline.py   # needs DATABASE_URL
```

### NBA — running in prod with known fixes pending deploy

| Area | Status |
|------|--------|
| `NBA_PHASES` | Full daily path (~28 YetiBets steps consolidated) |
| PRA / per-stat XGBoost | Working in prod logs |
| Totals projector | Failed `TeamRoster.team_name` → fixed `d6bed95e`; failed `db.session` → fixed `1b11cb7b` |
| Accuracy grading | `calculate_prediction_accuracy` (player stats); totals use **`NBATotalsAccuracy`** (not `PredictionAccuracy`) |
| API / UI gaps | No totals on `/api/v1/predictions/nba` or `/predictions/nba` yet |

**Local checks:**

```bash
cd backend
PYTHONPATH=. pytest tests/test_nba_totals_projector.py -v
PYTHONPATH=. python scripts/validate_nba_pipeline.py
```

### NFL / NHL — stubs

Orchestrators return `skeleton_only`. UI shells exist; no daily ETL data yet.

---

## Tooling added (2026-05-20)

| Tool | Purpose |
|------|---------|
| `scripts/smoke_import_mlb_etl.py` | Import all `app.services/etl.mlb.*` modules before deploy |
| `tests/test_nba_totals_projector.py` | `load_team_data`, `save_projection` Session API |
| `scripts/validate_mlb_pipeline.py` | Expanded row counts (game/hits/blowouts) |
| `scripts/validate_nba_pipeline.py` | Totals projections + totals accuracy tables |
| `scripts/enqueue_mlb_pipeline.py` | Enqueue MLB pipeline when Redis healthy |
| `POST /api/admin/celery/enqueue-task` | Fire-and-forget orchestrators (needs API deploy) |

---

## Production verification checklist (when deploys resume)

1. Confirm Redis: TCP to `redis.railway.internal:6379` from worker.
2. Redeploy **celery-worker** and **API** from `main` (≥ `dc1b56ba`).
3. Enqueue MLB (async only):

   ```bash
   railway ssh -- bash -lc 'cd /app/backend && PYTHONPATH=/app/backend python3 scripts/enqueue_mlb_pipeline.py'
   ```

4. Tail logs for `MLB projections pipeline starting` and no `ModuleNotFoundError`.
5. Run validators on worker:

   ```bash
   PYTHONPATH=/app/backend python3 scripts/validate_mlb_pipeline.py
   PYTHONPATH=/app/backend python3 scripts/validate_nba_pipeline.py
   ```

6. Enqueue or wait for Beat: `run_nba_update_pipeline` — confirm totals rows in `pred_nba_totals_projections`.

---

## Next build candidates (no Railway required)

- [ ] NBA totals on predictions API + frontend
- [ ] `mlb_ev` Celery task → `pred_value_bets`
- [ ] MLB subtasks in `ADMIN_FIREABLE_TASKS` for incremental debug
- [ ] Pipeline `_run_phases` partial-failure status when a task errors
- [ ] NHL or NFL port (see stubs in `etl_pipeline.py`)

---

## Session log

### 2026-05-20 — Local verification batch

- Added MLB import smoke test, NBA totals unit tests, expanded validators, this status doc.
- **NBA unit tests:** `pytest tests/test_nba_totals_projector.py` — **6/6 passed** (venv + pytest installed).
- **MLB import smoke (pipeline-critical, 20 modules):** **6/20 passed** on laptop venv — failures are missing deps (`pandas`, `statsapi`, `numpy`), not import-path bugs. Passed: `_db`, `_venues`, `game_projection_pipeline`, `mlb_pitcher_analysis`, `mlb_batter_analysis`, `pipeline`. Re-run on worker or after `pip install -r requirements.txt` (matches Docker image).
- **Validators:** expanded; run against prod DB when `DATABASE_URL` is set.

```bash
cd backend
.venv/bin/pip install pytest   # once
PYTHONPATH=. .venv/bin/python scripts/smoke_import_mlb_etl.py
PYTHONPATH=. .venv/bin/python -m pytest tests/test_nba_totals_projector.py -v
PYTHONPATH=. .venv/bin/python scripts/validate_mlb_pipeline.py
PYTHONPATH=. .venv/bin/python scripts/validate_nba_pipeline.py
```
