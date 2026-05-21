# YetiBets → YetAI ETL migration status

Living document for the YetiBets → YetAI ETL migration. Update after each production verification run.

**Reference (read-only):** `YetiBets/`  
**Target:** `YetAI/YetAI/backend/` — Celery on `celery-worker`, Beat schedules in `app/celery_app.py`

---

## Last updated

| Field | Value |
|-------|--------|
| Date | 2026-05-21 |
| Branch / tip | `main` — MLB ML ops admin API + Celery retrain/HR rebuild |
| Railway | API + celery-worker deployed; GitHub `RAILWAY_TOKEN` configured |
| Infra | `/health` healthy; DB connected |
| **Prod ETL verified** | NHL verified; MLB daily + actuals exercised via admin Celery |

---

## Production verification (complete this checklist)

### Option A — Admin UI (fastest after API deploy)

1. Log in as admin → `/admin` → **ETL pipelines (Celery)**.
2. **Test worker** → ping OK.
3. **Enqueue all + verify** (or enqueue each sport, wait ~10–30 min, then **Verify data**).
4. Overall should be `verified` (NFL may be `verified_with_warnings` off-season).
5. Open `/predictions/mlb`, `/nba`, `/nhl`, `/nfl` — boards populated on game days.

### Option B — CLI

```bash
cd backend
export YETAI_ADMIN_JWT='...'   # localStorage auth_token while logged into yetai.app

# Check DB row counts (no enqueue)
PYTHONPATH=. python3 scripts/prod_verify_etl.py

# Enqueue all five orchestrators, poll up to 2h, re-verify
PYTHONPATH=. python3 scripts/prod_verify_etl.py --enqueue-all --wait 7200
```

### Option C — curl

```bash
curl -s -X POST "https://api.yetai.app/api/admin/celery/verify-etl" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"enqueue_all": false}' | jq .
```

Poll a pipeline: `GET /api/admin/celery/task-status/{task_id}`

### Option D — Railway SSH (validators only)

```bash
railway ssh --service celery-worker -- bash -lc \
  'cd /app/backend && PYTHONPATH=/app/backend python3 scripts/validate_mlb_pipeline.py'
# repeat: validate_nba_pipeline.py, validate_nhl_pipeline.py, validate_nfl_pipeline.py
```

---

## Sport pipelines — prod verified

| Sport | Orchestrator | Beat (ET) | Prod verified | Notes |
|-------|--------------|-----------|---------------|-------|
| MLB | `run_mlb_update_pipeline`, `run_mlb_store_actuals` | 10:00, 4:30 | ✅ | 2026-05-20/21 admin: K archive + actuals ok; verify-etl |
| NBA | `run_nba_update_pipeline` | 3:30 | ✅ | 2026-05-20 verify: points ≥ 8, pra ≥ 5 |
| NHL | `run_nhl_update_pipeline` | 5:00 | ✅ | 2026-05-20 verify-etl `verified` |
| NFL | `run_nfl_update_pipeline` | 4:30 | ☐ | Off-season May–Aug: orchestrator only |

After verification, change ☐ → ✅ and add date in **Session log**.

---

## Sport summaries

### MLB — code complete

| Area | Status |
|------|--------|
| Celery | `run_mlb_update_pipeline`, `run_mlb_store_actuals` |
| Modules | ~40+ under `app/services/etl/mlb/` (`MLB_ETL_PARITY.md`) |
| Not on Beat | `mlb_ev`, HR ML (S3); offline ML ops: `scripts/mlb_backtest.py`, `mlb_retrain_strikeouts.py`, `mlb_hr_rebuild.py` (`MLB_ML_OPS.md`) |

### NBA

| Area | Status |
|------|--------|
| `NBA_PHASES` | Full daily path + `nba.totals_projector` |
| API | `GET /api/v1/predictions/nba` → `totals` |

### NHL

| Area | Status |
|------|--------|
| `NHL_PHASES` | ingest + `nhl.daily_predictions` |
| Not ported | `confirm_starters`, live poller, backfill CLIs |

### NFL

| Area | Status |
|------|--------|
| `NFL_PHASES` | actuals → `qb_weekly` → `kickers` |
| Not ported | ML `.pkl` ensemble, warehouse FG models |
| Off-season | Validators pass without prediction rows |

---

## Admin & ops

| Tool | Purpose |
|------|---------|
| `POST /api/admin/celery/verify-etl` | **All-sport DB verification** (+ optional enqueue) |
| `GET /api/admin/celery/ml-ops-status` | Strikeout counts, S3 model heads, backtest index |
| `POST /api/admin/celery/ml-ops/retrain-strikeouts` | Enqueue prod K classifier retrain |
| `POST /api/admin/celery/ml-ops/hr-rebuild` | Enqueue one HR rebuild stage |
| `GET /api/admin/celery/task-status/{id}` | Poll orchestrator result |
| `POST /api/admin/celery/enqueue-task` | Fire one orchestrator |
| `/admin` → ETL panel | Enqueue, verify, worker ping |
| `scripts/prod_verify_etl.py` | CLI wrapper for verify-etl |
| `scripts/prod_mlb_strikeout_counts.py` | Prod strikeout projections/actuals/joined via API |
| `RAILWAY_DEPLOYMENT.md` | Redis, enqueue, SSH validators |

Beat schedule (`app/celery_app.py`): NBA 3:30, MLB actuals 4:30, NFL 4:30, NHL 5:00, MLB projections 10:00 ET.

---

## Parity docs

| Doc | Sport |
|-----|-------|
| `MLB_ETL_PARITY.md` | MLB |
| `NBA_ETL_PARITY.md` | NBA |
| `NHL_ETL_PARITY.md` | NHL |
| `NFL_ETL_PARITY.md` | NFL |

---

## Deferred parity (2026-05-20)

See `DEFERRED_PARITY.md` — wired: **MLB EV**, **HR ML** (env-gated), **NFL kicker ML ensemble**, **NHL odds edges**.

## Next (optional, post-verification)

- [ ] NFL Beat timing (e.g. Tue AM post-MNF) if 4:30 daily is wrong in-season
- [ ] NHL `confirm_starters.py`, NFL QB yards ML (`advanced_qb_predictor`)
- [ ] `scripts/enqueue_nfl_pipeline.py` helper

---

## Session log

### 2026-05-21 — MLB ML ops phase 2

- `GET /api/admin/celery/ml-ops-status`, retrain/HR rebuild enqueue routes.
- Celery: `mlb.retrain_strikeout_classifier`, `mlb.hr_rebuild_stage`, `mlb.backtest_quick`.
- `scripts/prod_mlb_strikeout_counts.py`, `mlb_backtest_list_runs.py`.
- Strikeout retrain guardrail: `MLB_STRIKEOUT_MIN_JOINED_ROWS` (default 50).

### 2026-05-20 — Production verification

- NHL `verify-etl` → **verified** (7 games, predictions after dedupe fix).
- MLB admin Celery: strikeouts + `store_strikeout_projections` (30 rows); `run_mlb_store_actuals` all phases ok after `hits.py` date fix.
- NBA verify thresholds relaxed for playoff slates.

### 2026-05-20 — Verification tooling

- Added `app/services/etl/prod_verification.py`, `app/api/admin_celery_ops.py` (`verify-etl`, `task-status`).
- Added `scripts/prod_verify_etl.py`, Admin UI **Verify data** / **Enqueue all + verify**.
- NFL validator skips prediction rows off-season (May 2026).

### 2026-05-20 — Production redeploy

- `origin/main`; Railway deploy green; `/health` OK.

### 2026-05-20 — NFL port + CI + Railway

- `NFL_PHASES`, validators, `NFL_ETL_PARITY.md`, backend CI fixes, `RAILWAY_TOKEN` project secret.
