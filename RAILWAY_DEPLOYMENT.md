# Railway Deployment Guide

## Overview
This document describes the simplified, reliable deployment strategy for YetAI backend on Railway.

## Architecture

```
GitHub (main branch)
    |
    | (auto-deploy on push)
    v
Railway Platform
    |
    +-- Build: Dockerfile (backend/Dockerfile)
    |
    +-- Deploy: uvicorn on $PORT
    |
    +-- Health Check: /health endpoint
```

## Deployment Files

### 1. `/railway.json` (Root)
Primary Railway configuration file that defines:
- **Builder**: Dockerfile mode
- **Dockerfile Path**: `backend/Dockerfile`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
- **Health Check**: `/health` endpoint with 300s timeout
- **Restart Policy**: ON_FAILURE

### 2. `/backend/Dockerfile`
Production-ready Docker container with:
- Python 3.11 slim base image
- System dependencies (gcc, g++, libpq-dev, curl)
- pip dependencies from requirements.txt
- Non-root user (appuser) for security
- Dynamic PORT handling via environment variable
- Health check with curl

### 3. `.github/workflows/backend-ci-cd.yml`
CI/CD pipeline that runs on push to main:
- Linting and code quality checks
- Security scanning (Bandit, Safety)
- Unit tests with coverage
- Health check after Railway auto-deploys

## Environment Variables

Set these in Railway dashboard:

### Required
- `DATABASE_URL` - Set automatically by Railway PostgreSQL plugin
- `PORT` - Set automatically by Railway (typically 8000-9000 range)
- `SECRET_KEY` - Your application secret key

### Email (SMTP via Brevo)
- `SMTP_HOST` - `smtp-relay.brevo.com`
- `SMTP_PORT` - `587`
- `SMTP_USER` - `9901af001@smtp-brevo.com` (UPDATE FROM OLD VALUE!)
- `SMTP_PASSWORD` - `swzM8yBHR7VZAh6j`
- `FROM_EMAIL` - `yetai.help@gmail.com`

### Optional
- `ENVIRONMENT` - `production` (default)
- `OPENAI_API_KEY` - For AI features
- `STRIPE_API_KEY` - For payment processing

## Deployment Process

### Automatic Deployment (Recommended)
1. Push code to `main` branch
2. Railway automatically detects changes
3. Railway builds Docker image from `backend/Dockerfile`
4. Railway runs health check on `/health`
5. Railway switches traffic to new deployment
6. GitHub Actions validates deployment

### Manual Deployment (Emergency)

**GitHub Actions:** secret `RAILWAY_TOKEN` only (production project token). See `CICD_SETUP.md`.

```bash
npm i -g @railway/cli@latest
railway logout
unset RAILWAY_API_TOKEN   # only one token env var at a time
export RAILWAY_TOKEN='...'

railway up --detach --service 9fe8f0dc-96ac-408f-9960-950768e6eb49
```

## Health Check

The `/health` endpoint returns:
```json
{
  "status": "healthy",
  "timestamp": "2025-10-10T21:51:00Z",
  "database": "connected",
  "environment": "production"
}
```

Health check configuration:
- **Path**: `/health`
- **Timeout**: 300 seconds
- **Start Period**: 40 seconds (Docker healthcheck)
- **Interval**: 30 seconds

## Service IDs (`yetai-backend` / production)

| Service | Name | ID |
|---------|------|-----|
| API (`api.yetai.app`) | `YetAI` | `9fe8f0dc-96ac-408f-9960-950768e6eb49` |
| Celery + Beat | `celery-worker` | `9b9982f4-82b7-4e0f-88a0-3212221fecf4` |
| Postgres | `Postgres` | `421f0104-94c9-478a-8f11-d19955df0d37` (do not use for `railway up`) |

Copy IDs: Railway project → Cmd+K → copy service/environment ID.

## Celery worker (`celery-worker` service)

The API and worker share `backend/Dockerfile`. Two common failures:

1. **Wrong Docker build context** — if the worker builds from the **repo root** instead of `backend/`, the image has `/app/backend/app/` not `/app/app/`. `PYTHONPATH=/app` cannot fix that; use `PYTHONPATH=/app/backend` or fix build settings below.
2. **Custom start command bypasses ENTRYPOINT** — use the start script, not bare `celery -A ...`.

### Worker settings (must match API)

In Railway → **celery-worker** → **Settings**:

| Setting | Correct value |
|--------|----------------|
| **Root Directory** | Same as API (usually empty = repo root, or `backend`) |
| **Builder** | Dockerfile |
| **Dockerfile** | If root is repo root: `backend/Dockerfile` + variable `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile` if needed |
| **Config file** | Root `railway.json` sets `"dockerContext": "backend"` — worker must be in the same project and not override builder to Nixpacks |

Compare **Build logs** on API vs worker: both should show `Using detected Dockerfile` and the same context. If worker image layout is wrong, run a one-off start command to confirm:

```text
bash -c 'ls -la /app/app 2>&1; ls -la /app/backend/app 2>&1'
```

### Worker start command

After deploy includes `scripts/railway-celery.sh`:

```text
/app/scripts/railway-celery.sh
```

**Immediate workaround** (repo-root context, no new deploy):

```text
bash -c 'cd /app/backend && PYTHONPATH=/app/backend exec celery -A app.celery_app worker --beat --loglevel=info --concurrency=1'
```

Do not use bare `celery -A app.celery_app ...` without resolving `APP_ROOT` first.

After changing the start command or `backend/Dockerfile`, redeploy the worker:

```bash
railway service          # link celery-worker
railway redeploy -y
railway logs --deployment
```

Success looks like a Celery banner with `transport: redis://...`, not `No module named 'app'`.

Ensure `REDIS_URL` on the worker references the Railway Redis plugin (not `localhost:6379`).

## ETL pipeline runbook (ops)

Use this when validating MLB/NBA/NHL/NFL migrations or recovering after an outage. Prefer the **API** or **Admin UI** (Admin → ETL pipelines) over SSH for enqueue.

Full cross-sport checklist: `backend/docs/ETL_MIGRATION_STATUS.md` (post-deploy verification matrix).

### 1. Redis / worker health

```bash
# From your laptop (admin JWT)
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://api.yetai.app/api/admin/celery/health | jq .

# Ping should return status "ok". If timeout/error, fix Redis first:
railway logs --service celery-worker | tail -80
```

Worker logs must show `transport: redis://...` (not `localhost:6379`). Beat/worker `SchedulingError: Timeout connecting to server` means Redis is down or unreachable.

### 2. Enqueue a full pipeline (recommended)

**Do not** run `celery call app.tasks.etl_pipeline.run_mlb_update_pipeline` over SSH — it blocks for the entire run and often hangs when Redis is slow.

**Admin UI:** `/admin` → **ETL pipelines (Celery)** → **Enqueue pipeline**.

**API (fire-and-forget):**

```bash
curl -s -X POST "https://api.yetai.app/api/admin/celery/enqueue-task" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task_name":"app.tasks.etl_pipeline.run_mlb_update_pipeline"}' | jq .
```

Allowed `task_name` values:

| Task | Purpose |
|------|---------|
| `app.tasks.etl_pipeline.run_mlb_update_pipeline` | Daily MLB projections |
| `app.tasks.etl_pipeline.run_mlb_store_actuals` | MLB post-game actuals |
| `app.tasks.etl_pipeline.run_nba_update_pipeline` | Full NBA daily ETL |
| `app.tasks.etl_pipeline.run_nhl_update_pipeline` | NHL ingest + goalie/SOG/totals automation |
| `app.tasks.etl_pipeline.run_nfl_update_pipeline` | NFL weekly: actuals → QB yards + lines → kickers |

**On the worker** (after deploy includes `scripts/enqueue_mlb_pipeline.py`):

```bash
railway ssh --service celery-worker -- bash -lc \
  'cd /app/backend && PYTHONPATH=/app/backend python3 scripts/enqueue_mlb_pipeline.py'
```

### 3. Run a single ETL step (debug)

For one step without the full orchestrator, use **fire-and-wait** (admin allow-list, timeouts in `ADMIN_FIREABLE_TASKS`):

```bash
curl -s -X POST "https://api.yetai.app/api/admin/celery/run-task?task_name=app.tasks.etl_pipeline.mlb.strikeouts" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq .
```

Examples: `mlb.strikeouts`, `mlb.hits`, `nba.totals_projector`, `mlb.ev`, `nhl.daily_predictions`, `nfl.qb_weekly`, `nfl.kickers`.

### 4. Validate prediction tables

SSH to worker (or any service with `DATABASE_URL` + deps):

```bash
railway ssh --service celery-worker -- bash -lc \
  'cd /app/backend && PYTHONPATH=/app/backend python3 scripts/validate_mlb_pipeline.py'

railway ssh --service celery-worker -- bash -lc \
  'cd /app/backend && PYTHONPATH=/app/backend python3 scripts/validate_nba_pipeline.py'

railway ssh --service celery-worker -- bash -lc \
  'cd /app/backend && PYTHONPATH=/app/backend python3 scripts/validate_nhl_pipeline.py'

railway ssh --service celery-worker -- bash -lc \
  'cd /app/backend && PYTHONPATH=/app/backend python3 scripts/validate_nfl_pipeline.py'
```

Local (with venv + `DATABASE_URL`):

```bash
cd backend
PYTHONPATH=. python3 scripts/validate_mlb_pipeline.py
PYTHONPATH=. python3 scripts/validate_nba_pipeline.py
```

Import smoke (no DB):

```bash
PYTHONPATH=. python3 scripts/smoke_import_mlb_etl.py
```

### 5. Read pipeline results

Orchestrators return Celery results with:

- `status`: `ok` or `partial_failure` (any sub-task error in a phase)
- `failed_tasks` / `critical_failed_tasks`: Celery task names that errored
- `phases[].results[]`: each entry has `critical: true|false` and `result` or `error`

Tail worker logs while a pipeline runs:

```bash
railway logs --service celery-worker --deployment
```

Look for `partial_failure`, `failed_tasks`, and `ModuleNotFoundError` after deploys.

### 6. Deploy checklist after code changes

1. Push to `main` → wait for API **and** `celery-worker` deploy (deploys must be unpaused).
2. Confirm `GET /api/admin/celery/pipeline-catalog` returns 200 (new UI depends on this).
3. `GET /api/admin/celery/health` → ping OK.
4. Enqueue MLB or NBA pipeline → watch logs → run validate scripts.

## Troubleshooting

### Deployment Fails to Start
1. Check Railway logs for PORT binding errors
2. Verify environment variables are set correctly
3. Ensure database connection is working
4. Check that health endpoint is responding

### Old Code Running
This was caused by multiple conflicting config files. Now fixed with:
- Single source of truth: `railway.json`
- Explicit Dockerfile path: `backend/Dockerfile`
- Clear start command in railway.json

### PORT Variable Not Expanding
**Solution**: Use shell form in Dockerfile CMD (not exec form)
```dockerfile
# CORRECT - Shell form allows env var expansion
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}

# WRONG - Exec form doesn't expand variables
CMD ["uvicorn", "app.main:app", "--port", "$PORT"]
```

## Rollback Procedure

If deployment fails:
1. Railway automatically keeps previous deployment running
2. Manual rollback: Railway dashboard > Deployments > Select previous > Redeploy
3. Emergency: `git revert <commit-hash>` and push to main

## Performance Tuning

Current settings:
- **Workers**: 1 (Railway hobby plan has limited memory)
- **Worker Class**: uvicorn default (async)
- **Timeout**: 300 seconds
- **Keep-Alive**: Default (5 seconds)

For production scaling:
- Increase workers based on available memory (2-4 workers)
- Monitor memory usage in Railway metrics
- Consider upgrading Railway plan for better resources

## Monitoring

### Railway Dashboard Metrics
- CPU usage
- Memory usage
- Request latency
- Error rates

### Custom Monitoring
- Application logs via Railway CLI: `railway logs`
- Health check endpoint: `curl https://api.yetai.app/health`
- Database connection: `curl https://api.yetai.app/test-db`

## Security

- Non-root user in Docker container
- Environment variables never committed to git
- Security scanning in CI/CD pipeline
- Regular dependency updates
- HTTPS enforced by Railway

## Cost Optimization

- Single worker for hobby plan
- Efficient Docker layer caching
- Minimal system dependencies
- Health check timeout prevents zombie containers

## Next Steps

1. Update SMTP_USER in Railway dashboard to `9901af001@smtp-brevo.com`
2. Monitor first deployment with new configuration
3. Test email verification system
4. Set up alerts for deployment failures
5. Document any custom environment variables

## Support

- Railway Docs: https://docs.railway.app
- Railway Discord: https://discord.gg/railway
- GitHub Issues: https://github.com/benyetra/YetAI/issues
