# Fantasy (Sleeper) — runbook

End-to-end guide for fantasy features without chat context. **Platform:** Sleeper only (ESPN/Yahoo connect UI may exist but backend targets Sleeper).

## Architecture

| Layer | Location |
|-------|----------|
| API routers | `app/api/fantasy/` (connect, recommendations, trade analyzer, legacy analytics, matchups) + `app/api/fantasy_analytics.py` (`/api/v1/fantasy/analytics/*`) |
| Connection / leagues | `app/services/fantasy_connection_service.py` |
| Sleeper HTTP | `app/services/sleeper_fantasy_service.py`, `app/services/fantasy_sleeper_unified.py` |
| Projections | `app/services/fantasy_projections.py`, `app/services/fantasy_pipeline.py` |
| Start/sit helpers | `app/services/start_sit_service.py`, `app/services/player_analytics_service.py` |
| ETL (nflverse → DB) | `app/services/etl/fantasy/sync_player_analytics.py` |
| Frontend | `frontend/src/pages/FantasyPage.tsx` (or equivalent route `/fantasy`) |
| E2E (stubbed API) | `frontend/tests/fantasy-happy-path.spec.ts`, `frontend/tests/fixtures/fantasy-auth.fixture.ts` |
| Backend tests | `backend/tests/test_fantasy_routes.py`, `test_fantasy_projections.py`, `test_fantasy_player_analytics_etl.py`, `test_fantasy_sleeper_unified.py` |

## Environment

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes | Postgres — `fantasy_players`, `player_analytics`, user connections |
| `REDIS_URL` | Celery only | Broker for scheduled analytics sync |
| JWT / auth secrets | Yes (prod) | Same as main app — fantasy routes use `get_current_user` |

No Sleeper API key — Sleeper’s public REST API is unauthenticated.

### Local Python deps (analytics ETL)

`nfl-data-py` is required for `sync_player_analytics` (not installed as a normal pip dep because of version pins):

```bash
cd backend
.venv/bin/pip install nfl-data-py==0.3.3 --no-deps
.venv/bin/pip install appdirs fastparquet
```

Docker image installs the same set (see `backend/Dockerfile`).

## Data pipeline

### What gets synced

1. **`fantasy_players`** — Sleeper player catalog (GSIS ↔ Sleeper ID mapping). Heavy (~6 min first run); optional on manual ETL.
2. **`player_analytics`** — Weekly nflverse stats mapped to internal player IDs; powers start/sit, projections, trade context. GSIS mapping uses Sleeper `gsis_id` when present, then falls back to nflverse `import_ids()` (covers players like Jahmyr Gibbs where Sleeper omits `gsis_id`).

### Manual ETL (fast path — analytics only)

Uses nflverse weekly player stats. Seasons through 2024 load via `nfl-data-py`
(`player_stats_{season}.parquet`). **2025+** fall back to
`stats_player_week_{season}.parquet` when the legacy URL 404s.

```bash
cd backend
PYTHONPATH=. .venv/bin/python -c "
from app.services.etl.fantasy.sync_player_analytics import run
print(run(season=2024))
"
```

Expected on a warm DB: `rows_upserted: 0`, `rows_unchanged: ~1547`, `fantasy_players_sync: None`.

### Full sync (catalog + analytics)

```bash
PYTHONPATH=. .venv/bin/python -c "
from app.services.etl.fantasy.sync_player_analytics import run
print(run(season=2024, sync_fantasy_players=True))
"
```

Use after Sleeper roster changes or first-time setup.

### Celery (production)

| Beat key | Task | Schedule |
|----------|------|----------|
| `fantasy-player-analytics-weekly` | `app.tasks.etl_pipeline.fantasy.sync_player_analytics` | Tue 06:30 UTC (after MNF) |

Celery task calls `run(..., sync_fantasy_players=True)` so production refreshes the Sleeper catalog weekly.

### Production verification checklist

Run after each backend deploy that touches fantasy ETL or Celery (`backend/**`, `railway.json`, worker image).

| Step | How | Pass criteria |
|------|-----|---------------|
| 1. Deploy | GitHub **Railway Production Deploy** (or push to `main` with backend changes) | API + `celery-worker` services on latest commit |
| 2. Beat schedule | Railway → worker logs or admin Celery UI | `fantasy-player-analytics-weekly` registered (Tue 06:30 UTC) |
| 3. Current-season backfill | Railway shell or one-off task (see below) | `rows_upserted` > 0 on first run, then `rows_unchanged` ≈ prior count |
| 4. Mapping health | Check task result fields | `fantasy_players_mapped` ≈ 1000+; high `rows_skipped` is normal (~90% nflverse rows lack GSIS map) |
| 5. UI smoke | Logged-in user on `/fantasy` | Connect → league card → start/sit returns recommendations for current week |

**One-off 2025 backfill (production shell):**

```bash
cd backend
PYTHONPATH=. python -c "
from app.services.etl.fantasy.sync_player_analytics import run
print(run(season=2025))
"
```

**One-off backfill from your Mac (via Railway public Postgres URL):**

Railway’s internal `postgres.railway.internal` hostname is not reachable from a local machine. Use `DATABASE_PUBLIC_URL` from the **Postgres** service (proxy host, e.g. `shuttle.proxy.rlwy.net`):

```bash
cd backend
PUBLIC_URL=$(railway variables --service Postgres --json \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])")

DATABASE_URL="$PUBLIC_URL" DATABASE_PUBLIC_URL="$PUBLIC_URL" \
PYTHONPATH=. .venv/bin/python -c "
from app.services.etl.fantasy.sync_player_analytics import run
print(run(season=2025, sync_fantasy_players=True))
"
```

Pass criteria: `rows_upserted` > 0 on first run after mapping fixes; `fantasy_players_mapped` ≈ 2000+; re-run shows mostly `rows_unchanged`. API service name on Railway is **YetAI** (not `api`).

Expected first run: `rows_upserted` ~1400+, `fantasy_players_sync` set if Celery path (`sync_fantasy_players=True`). Re-run should show `rows_unchanged` with `rows_upserted: 0` in ~5–10s.

**Verify Celery task manually:**

```bash
PYTHONPATH=. python -c "
from app.tasks.etl_pipeline import fantasy_sync_player_analytics
print(fantasy_sync_player_analytics.delay(season=2025))
"
```

Monitor worker logs for completion and no `HTTP Error 404` on weekly parquet (2025+ requires `stats_player_week` fallback from commit `0f3db7b7` onward).

**Automated prod verify script (Railway shell or local with `DATABASE_URL`):**

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/prod_verify_fantasy.py --season 2025
```

Optional API smoke after deploy (requires a user JWT):

```bash
PYTHONPATH=. .venv/bin/python scripts/prod_verify_fantasy.py \
  --season 2025 \
  --api-url https://api.yetai.app \
  --token "$AUTH_TOKEN" \
  --week 1
```

Pass criteria: beat schedule registered, `fantasy_players_mapped` ≥ 1000, `player_analytics_rows` > 0 for the season, optional start/sit HTTP 200.

**Mapping health audit (no DB writes):**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -c "
import asyncio
from app.core.database import SessionLocal
from app.services.etl.fantasy.sync_player_analytics import audit_player_analytics_mapping
db = SessionLocal()
print(asyncio.run(audit_player_analytics_mapping(db, season=2025)))
db.close()
"
```

High `skip_rate_pct` (~90%) is normal: most nflverse rows lack a GSIS↔Sleeper map. Focus on `fantasy_players_mapped` and `player_analytics_rows`.

Manual enqueue:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -c "
from app.tasks.etl_pipeline import fantasy_sync_player_analytics
print(fantasy_sync_player_analytics.delay(season=2024))
"
```

## API route map

### Legacy `/api/fantasy/*` (frontend primary)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/fantasy/accounts` | Connected Sleeper accounts |
| GET | `/api/fantasy/leagues` | User’s leagues |
| POST | `/api/fantasy/connect` | Body: `{ platform, credentials }` — Sleeper: `{ username }` |
| DELETE | `/api/fantasy/disconnect/{fantasy_user_id}` | Remove connection |
| POST | `/api/fantasy/sync-league/{league_id}` | Persist league metadata |
| GET | `/api/fantasy/roster/{league_id}` | User roster via `fantasy_pipeline` |
| GET | `/api/fantasy/projections` | Top-N projections from analytics |
| GET | `/api/fantasy/players/search?q=` | Sleeper name search (min 2 chars) |
| GET | `/api/fantasy/recommendations/start-sit/{week}` | Optional `?league_id=` |
| GET | `/api/fantasy/recommendations/waiver-wire/{week}` | Trending adds/drops |
| GET | `/api/fantasy/leagues/{league_id}/rules` | Scoring + roster settings |
| GET | `/api/fantasy/matchups/{league_id}/{week}` | H2H matchups |
| GET | `/api/fantasy/trending` | `?trend_type=add\|drop&limit=` |
| GET | `/api/fantasy/analytics/{player_id}` | Legacy shim (Sleeper ID) |
| GET | `/api/fantasy/analytics/{player_id}/trends` | Weekly trend series |
| GET | `/api/fantasy/analytics/{player_id}/efficiency` | Efficiency metrics |
| POST | `/api/fantasy/players/compare` | 2–4 Sleeper player IDs |
| GET | `/api/fantasy/players/{player_id}/analytics/{season}` | Season rollup |
| GET | `/api/fantasy/test/sleeper/{username}` | Pre-connect validation |

### Versioned `/api/v1/fantasy/*`

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/fantasy/standings/{league_id}` | Sorted standings |
| GET | `/api/v1/fantasy/trade-analyzer/team-analysis/{team_id}` | `?league_id=` required |
| POST | `/api/v1/fantasy/trade-analyzer/recommendations` | Trade suggestions |
| GET | `/api/v1/fantasy/trade-analyzer/player-values` | Value board |
| POST | `/api/v1/fantasy/trade-analyzer/quick-analysis` | Lightweight trade check |
| * | `/api/v1/fantasy/analytics/*` | Rich analytics (`fantasy_analytics.py`) |

OpenAPI: `/docs` after `PYTHONPATH=. .venv/bin/python scripts/export_openapi.py`.

## Local dev — backend + frontend

```bash
# Terminal 1 — API
cd backend
source .venv/bin/activate   # or use .venv/bin/uvicorn directly
PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload --port 8000

# Terminal 2 — UI
cd frontend
npm run dev
```

Visit `http://localhost:5173/fantasy` (Vite port may vary).

## Manual E2E verification (real Sleeper)

1. **Auth** — Log in; JWT stored client-side.
2. **Connect** — POST `/api/fantasy/connect` with `{ "platform": "sleeper", "credentials": { "username": "<sleeper_username>" } }`.
3. **Leagues** — GET `/api/fantasy/leagues` — pick `league_id`.
4. **Sync** — POST `/api/fantasy/sync-league/{league_id}`.
5. **Roster** — GET `/api/fantasy/roster/{league_id}`.
6. **Start/sit** — GET `/api/fantasy/recommendations/start-sit/1?league_id={id}` (week = current NFL week).
7. **Trending / waiver** — GET `/api/fantasy/trending` or waiver recommendation route.
8. **Matchups** — GET `/api/fantasy/matchups/{league_id}/{week}`.
9. **Trade analyzer** — Open UI modal; backend hits `/api/v1/fantasy/trade-analyzer/*`.

If start/sit returns empty recommendations, run analytics ETL for the season and confirm `player_analytics` rows exist for roster players.

## Automated E2E (Playwright, stubbed)

No real Sleeper or DB required — routes are mocked in the fixture. **CI:** `.github/workflows/frontend-ci-cd.yml` runs `npm run test:ci` (fantasy happy path only) after installing Chromium.

```bash
cd frontend
npm run test:ci
```

Covers: league card, trending, start/sit button, waiver button, matchups, trade analyzer shell.

## Backend tests

```bash
cd backend
python3 -m black .
PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_fantasy_routes.py tests/test_fantasy_projections.py tests/test_fantasy_player_analytics_etl.py tests/test_fantasy_sleeper_unified.py
```

Full gate before push: `PYTHONPATH=. .venv/bin/python -m pytest -q`.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| `ModuleNotFoundError: nfl_data_py` | Install nfl-data-py (see above) |
| `503 Fantasy pipeline service unavailable` | Service loader / `fantasy_pipeline` registration |
| Empty start/sit | `player_analytics` backfill; GSIS mapping in `fantasy_players` (re-run sync after mapping fixes) |
| `HTTP Error 404` on season 2025+ ETL | Legacy nfl-data-py URL; upgrade to latest code with `stats_player_week` fallback |
| Empty leagues after connect | Sleeper API is **season-scoped** (`/leagues/nfl/{year}`). Offseason, current calendar year may have 0 leagues — API fetches current + prior season. Verify with `curl https://api.sleeper.app/v1/user/{sleeper_id}/leagues/nfl/2025` |
| `Unknown PG numeric type` on analytics | `PlayerAnalytics.game_script` must be `Float`; run Alembic if schema drift |

## Related issues

Beads epic **YetAI-ojg** — fantasy MVP (routes, ETL, docs, Playwright).  
Phase 2: prod checklist (this doc), Playwright in CI, deterministic trade analyzer.
