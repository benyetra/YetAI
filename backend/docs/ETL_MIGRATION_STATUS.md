# YetiBets → YetAI ETL migration status

Living document while Railway deploys are paused (post-outage). Update after each local verification batch and after production runs.

**Reference (read-only):** `YetiBets/`  
**Target:** `YetAI/YetAI/backend/` — Celery on `celery-worker`, Beat schedules in `app/celery_app.py`

---

## Last updated

| Field | Value |
|-------|--------|
| Date | 2026-05-20 |
| Branch / tip | `origin/main` @ `f09e9b97` (NFL/NHL port + CI + Railway deploy fix) |
| Railway | API + celery-worker deployed; `RAILWAY_TOKEN` in GitHub Actions |
| Local tooling | MLB/NBA/NHL/NFL smoke + validators; admin enqueue API |
| **Next** | Run post-deploy matrix below (enqueue → validate → API/UI) |

---

## Sport pipelines (summary)

| Sport | Orchestrator | Beat | Prod verified |
|-------|--------------|------|---------------|
| MLB | `run_mlb_update_pipeline`, `run_mlb_store_actuals` | Yes | **Pending** — enqueue + validator after deploy |
| NBA | `run_nba_update_pipeline` | Yes | **Pending** — totals fixes now on `main` |
| NHL | `run_nhl_update_pipeline` | TBD | **Pending** |
| NFL | `run_nfl_update_pipeline` | **No** (enqueue / admin only) | **Pending** |

---

## MLB — code complete, prod not verified

| Area | Status |
|------|--------|
| Celery orchestration | `run_mlb_update_pipeline`, `run_mlb_store_actuals` wired |
| Module port | ~40+ modules under `app/services/etl/mlb/` (see `MLB_ETL_PARITY.md`) |
| **Production run** | **Not confirmed** after import fixes (Redis/outage blocked enqueue) |
| Not on Beat | `mlb_ev`, HR ML (needs S3 env), backtest/retrain CLIs |

```bash
cd backend
PYTHONPATH=. python3 scripts/smoke_import_mlb_etl.py
PYTHONPATH=. python3 scripts/validate_mlb_pipeline.py   # needs DATABASE_URL
```

---

## NBA — running in prod with fixes pending deploy

| Area | Status |
|------|--------|
| `NBA_PHASES` | Full daily path |
| Totals | `nba.totals_projector` + API `totals` + `/predictions/nba` |
| Known fixes | `TeamRoster.team_name`, `db.session` → Session API (commits on `main`) |

```bash
PYTHONPATH=. pytest tests/test_nba_totals_projector.py -v
PYTHONPATH=. python3 scripts/validate_nba_pipeline.py
```

---

## NHL — ported

`NHL_PHASES`: ingest + `nhl.daily_predictions`. See `NHL_ETL_PARITY.md`.

```bash
PYTHONPATH=. python3 scripts/smoke_import_nhl_etl.py
PYTHONPATH=. python3 scripts/validate_nhl_pipeline.py
```

---

## NFL — ported (weekly)

| Area | Status |
|------|--------|
| Modules | `app/services/etl/nfl/` — QB dynamic/betting, kickers, actuals collectors |
| Data | `backend/data/nfl/*.csv` in Docker image (`COPY . .`) |
| Orchestrator | `NFL_PHASES`: actuals → `qb_weekly` → `kickers` |
| Critical tasks | `nfl.qb_weekly`, `nfl.kickers` |
| API / UI | `GET /api/v1/predictions/nfl` + `/predictions/nfl` (pre-existing) |
| Not ported | ML ensemble `.pkl`, advanced QB warehouse, Beat schedule |

See `NFL_ETL_PARITY.md`.

```bash
PYTHONPATH=. python3 scripts/smoke_import_nfl_etl.py
PYTHONPATH=. python3 scripts/validate_nfl_pipeline.py   # in-season + after pipeline run
```

---

## Admin & ops

| Tool | Purpose |
|------|---------|
| `GET /api/admin/celery/pipeline-catalog` | Labels for enqueue buttons |
| `POST /api/admin/celery/enqueue-task` | Fire-and-forget orchestrators |
| `POST /api/admin/celery/run-task` | Sync single subtask (`ADMIN_FIREABLE_TASKS`) |
| `/admin` → Celery pipelines panel | Worker ping + enqueue |
| `scripts/enqueue_mlb_pipeline.py` | MLB enqueue when Redis healthy |
| `RAILWAY_DEPLOYMENT.md` | Redis, enqueue, validators, avoid `celery call` hang |

Pipeline semantics: `status: ok | partial_failure`; per-task `critical` in phase results.

---

## Post-deploy verification matrix

Run after **celery-worker** and **API** redeploy from a commit that includes NFL + latest NBA/NHL/MLB fixes.

### 0. Infrastructure

| Check | Command / action | Pass criteria |
|-------|------------------|---------------|
| Redis TCP | `railway ssh` → `nc -zv redis.railway.internal 6379` (or app health) | Connects in &lt;2s |
| Worker imports | `PYTHONPATH=/app/backend python3 scripts/smoke_import_mlb_etl.py` (on worker) | All critical MLB modules import |
| Worker ping | Admin UI or `GET /api/admin/celery/worker-ping` | At least one worker `ok` |

### 1. Enqueue orchestrators (async — do not use `celery call`)

| Sport | Task | Log pattern |
|-------|------|-------------|
| MLB | `run_mlb_update_pipeline` | `MLB projections pipeline starting` |
| MLB actuals | `run_mlb_store_actuals` | `MLB actuals pipeline starting` |
| NBA | `run_nba_update_pipeline` | `NBA update pipeline starting` |
| NHL | `run_nhl_update_pipeline` | `NHL update pipeline starting` |
| NFL | `run_nfl_update_pipeline` | `NFL update pipeline starting` |

Use Admin UI, `POST /api/admin/celery/enqueue-task`, or `scripts/enqueue_mlb_pipeline.py` for MLB.

**Pass:** orchestrator finishes with `"status": "ok"` (or `partial_failure` only if non-critical tasks failed — inspect `failed_tasks` / `critical_failed_tasks`).

### 2. DB validators (on worker, `DATABASE_URL` set)

```bash
cd /app/backend
PYTHONPATH=/app/backend python3 scripts/validate_mlb_pipeline.py
PYTHONPATH=/app/backend python3 scripts/validate_nba_pipeline.py
PYTHONPATH=/app/backend python3 scripts/validate_nhl_pipeline.py
PYTHONPATH=/app/backend python3 scripts/validate_nfl_pipeline.py
```

| Script | Tables exercised |
|--------|------------------|
| `validate_mlb_pipeline.py` | Game/hits/blowouts/strikeout boards |
| `validate_nba_pipeline.py` | Props + `pred_nba_totals_*` |
| `validate_nhl_pipeline.py` | Goalie, SOG, totals for today |
| `validate_nfl_pipeline.py` | `pred_qb_predictions`, `pred_kicker_predictions` (in-season) |

### 3. API smoke (API service, auth as needed)

| Endpoint | Expect |
|----------|--------|
| `GET /health` | 200 |
| `GET /api/v1/predictions/mlb` | `projected_hits` / `projected_homers` populated on game day |
| `GET /api/v1/predictions/nba` | `totals` array for today |
| `GET /api/v1/predictions/nhl` | `goalie_predictions`, `player_shots`, `team_totals` |
| `GET /api/v1/predictions/nfl` | `qb_predictions`, `kicker_predictions` after NFL pipeline |

### 4. Frontend pages

| Route | Expect |
|-------|--------|
| `/predictions/mlb` | Strikeout/hit boards |
| `/predictions/nba` | Props + totals section |
| `/predictions/nhl` | Goalie, SOG, totals tables |
| `/predictions/nfl` | QB + kicker tables |
| `/admin` | Enqueue buttons return `task_id`; worker ping green |

### 5. NFL-specific (in-season only)

| Step | Detail |
|------|--------|
| Env | `ODDS_API_KEY` set on worker (QB lines + kickers) |
| Subtask debug | Admin run-task: `nfl.qb_dynamic`, `nfl.qb_betting`, `nfl.kickers` |
| Data files | `ls /app/backend/data/nfl` — four CSVs present |
| Off-season | Validator may show empty prediction tables — expected |

### 6. Known failure modes

| Symptom | Likely cause |
|---------|----------------|
| `ModuleNotFoundError: scripts.enqueue_mlb_pipeline` | Worker image stale — redeploy |
| SSH `send_task` / `celery call` hangs | Unhealthy Redis — fix broker first |
| NBA totals empty | Deploy without `totals_projector` fix |
| NFL `partial_failure` on `qb_betting` | Missing/invalid `ODDS_API_KEY` |
| MLB smoke fails locally | Missing `pandas`/`statsapi` in laptop venv — run on worker |

---

## Parity docs

| Doc | Sport |
|-----|-------|
| `MLB_ETL_PARITY.md` | MLB |
| `NBA_ETL_PARITY.md` | NBA |
| `NHL_ETL_PARITY.md` | NHL |
| `NFL_ETL_PARITY.md` | NFL |

---

## Next (optional)

- [ ] NFL Celery Beat schedule (e.g. Tue AM after MNF grading)
- [ ] `scripts/enqueue_nfl_pipeline.py` mirroring MLB helper
- [ ] Port NFL ML ensemble / warehouse FG models
- [x] Railway deploys re-enabled (`railway up` + `RAILWAY_TOKEN` project secret)

---

## Session log

### 2026-05-20 — Production redeploy + verification start

- `origin/main` @ `f09e9b97`; API `/health` healthy in production.
- GitHub `RAILWAY_TOKEN` set; Railway Production Deploy workflow green.
- **In progress:** post-deploy matrix (enqueue orchestrators, validators, UI).

### 2026-05-20 — NFL port + post-deploy test matrix

- Wired `NFL_PHASES`, subtasks, `run_nfl_update_pipeline` (replaces `skeleton_only`).
- Fixed `qb_dynamic.py` / `qb_betting.py` imports; `py_compile` clean on all `etl/nfl/*.py`.
- Added `smoke_import_nfl_etl.py`, `validate_nfl_pipeline.py`, `NFL_ETL_PARITY.md`.
- Expanded this doc with cross-sport post-deploy verification matrix.
