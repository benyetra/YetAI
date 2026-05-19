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
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login to Railway
railway login

# Link to project
railway link

# Deploy manually
railway up
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
