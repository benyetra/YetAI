# YetAI

AI-powered sports betting and fantasy analytics platform. YetAI combines real-time odds, ML-driven predictions across major leagues, parlays, Sleeper fantasy sync, and an admin operations surface for ETL pipelines and automated picks.

| Surface | Production | Local dev |
|--------|------------|-----------|
| Web app | [yetai.app](https://yetai.app) | http://localhost:3000 |
| API | [api.yetai.app](https://api.yetai.app) | http://localhost:8000 |
| API docs | [api.yetai.app/docs](https://api.yetai.app/docs) | http://localhost:8000/docs |

Committed OpenAPI specs for agents and integrations: [docs/api/](docs/api/) (`openapi-public.json`, `openapi-admin.json`).

---

## What YetAI does

- **Predictions** — Daily and in-season models for MLB, NBA, NHL, NFL, and WNBA (player props, spreads, totals, strikeouts, and related markets). See [backend/docs/](backend/docs/) for per-sport ETL parity notes.
- **Betting** — Place and track bets, parlays, bet sharing, leaderboard, and performance views.
- **AI assistant** — In-app chat backed by OpenAI (when configured).
- **Fantasy** — Sleeper integration and fantasy analytics APIs. Runbook: [backend/docs/FANTASY.md](backend/docs/FANTASY.md).
- **Subscriptions** — Stripe checkout for upgrades (frontend + backend).
- **Admin** — Pipeline scheduling, Celery health, ETL enqueue/verify, Owens betting corner, user admin, and optional [automated YetAI picks](docs/runbooks/auto-yetai-picks.md) with approval workflow.

Background work runs on **Celery** (worker + beat) with **Redis** as the broker; the API is **FastAPI** on **PostgreSQL**.

---

## Architecture

```text
┌─────────────────┐     HTTPS/WSS      ┌──────────────────┐
│  Next.js 15     │ ◄────────────────► │  FastAPI (API)   │
│  (Vercel)       │                    │  (Railway)       │
└─────────────────┘                    └────────┬─────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
            ┌───────────────┐         ┌───────────────┐         ┌───────────────┐
            │  PostgreSQL   │         │  Redis        │         │  External APIs │
            │  (Railway)    │         │  (Railway)    │         │  Odds, OpenAI, │
            └───────────────┘         └───────┬───────┘         │  Stripe, etc.  │
                                              │                 └───────────────┘
                                              ▼
                                    ┌──────────────────┐
                                    │  celery-worker   │
                                    │  ETL + beat +    │
                                    │  live pollers    │
                                    └──────────────────┘
```

---

## Repository layout

```text
YetAI/
├── backend/                 # FastAPI app, Celery tasks, Alembic migrations, ETL
│   ├── app/                 # API routes, services, models, tasks
│   ├── alembic/             # Database migrations (source of truth for schema)
│   ├── docs/                # Sport ETL parity, migration status, ML ops
│   ├── scripts/             # Smoke tests, prod verify, pipeline helpers
│   ├── tests/               # pytest suite
│   ├── requirements.txt
│   ├── Dockerfile           # API + worker image (Railway)
│   └── .env.example
├── frontend/                # Next.js 15 (App Router), Tailwind 4, Playwright
│   └── src/app/             # Routes: predictions, bets, parlays, admin, …
├── database/                # Legacy local bootstrap (schema.sql + setup_db.sh)
├── scripts/                 # start_dev.sh — start API + frontend together
├── docs/                    # Runbooks, OpenAPI specs (docs/api/), plans
├── .github/workflows/       # CI/CD (backend, frontend, Railway deploy, migrations)
├── railway.json             # Railway Docker build config (API)
├── AGENTS.md                # Agent/contributor quick reference
├── CICD_SETUP.md            # GitHub secrets and deploy setup
└── RAILWAY_DEPLOYMENT.md    # Production Railway ops (health, Celery, ETL runbook)
```

---

## Prerequisites

| Requirement | Version / notes |
|-------------|-----------------|
| **Python** | 3.11 (matches CI and Docker) |
| **Node.js** | 18+ (CI uses 18; local 20+ is fine) |
| **PostgreSQL** | Local instance for development |
| **Redis** | Local instance (Celery broker; required for pipelines locally) |
| **API keys** | At minimum: Odds API; optional: OpenAI, Stripe, Google OAuth, Brevo, Twilio |

---

## Quick start (local)

### 1. Database

**Recommended:** use Alembic against a local Postgres database.

```bash
# Create DB user/db (or use your own DATABASE_URL)
cd database && ./setup_db.sh

cd ../backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — set DATABASE_URL, SECRET_KEY, ODDS_API_KEY, REDIS_URL, etc.

alembic upgrade head
```

The `database/` scripts are a convenience bootstrap; **schema changes belong in Alembic** under `backend/alembic/versions/`.

### 2. Redis

```bash
# macOS
brew services start redis
redis-cli ping   # expect PONG
```

### 3. Backend API

```bash
cd backend
source .venv/bin/activate
export PYTHONPATH=.
uvicorn app.main:app --reload --port 8000
```

### 4. Celery worker (optional but needed for ETL / auto-pick locally)

In a second terminal:

```bash
cd backend
source .venv/bin/activate
export PYTHONPATH=.
celery -A app.celery_app worker --beat --loglevel=info --concurrency=1
```

### 5. Frontend

```bash
cd frontend
npm ci
# Optional: .env.local with NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open http://localhost:3000. API docs: http://localhost:8000/docs.

### One-command dev (API + frontend only)

From repo root (uses `backend/.venv`, with fallback to `backend/venv`):

```bash
cd scripts && ./start_dev.sh
```

This script checks Postgres and Redis, activates the venv, sets `PYTHONPATH=.`, and starts uvicorn plus `npm run dev`. It does **not** start Celery — add a worker separately if you need background tasks.

---

## Environment variables

### Backend (`backend/.env`)

Copy from `backend/.env.example`. Common variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Celery broker / cache (`redis://localhost:6379` locally) |
| `SECRET_KEY` | JWT signing |
| `ODDS_API_KEY` | The Odds API (alias `ODDS_API` also accepted) |
| `OPENAI_API_KEY` | Chat / AI features |
| `STRIPE_SECRET_KEY` | Payments |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google sign-in |
| `BREVO_API_KEY` / `FROM_EMAIL` | Transactional email (production) |
| `ENVIRONMENT` | `development` \| `staging` \| `production` |
| `AUTO_YETAI_PICKS_ENABLED` | Enable scheduled auto-pick tasks (see runbook) |

Sport-specific optional keys (S3 ML artifacts, weather, etc.) are documented in `.env.example`.

### Frontend

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_URL` | Backend base URL (defaults to `https://api.yetai.app` on production hostnames) |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Google OAuth button |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | Stripe Embedded Checkout |
| `NEXT_PUBLIC_AUTO_YETAI_PICKS_ENABLED` | Show `/admin/yetai-picks` UI |

---

## Development workflow

| Change type | What to run |
|-------------|-------------|
| Backend Python | Auto-reload via `--reload`; format with Black before commit |
| Frontend | `npm run dev` (Turbopack) |
| DB schema | `cd backend && alembic revision --autogenerate -m "..."` then `alembic upgrade head` |
| API routes / OpenAPI | `cd backend && PYTHONPATH=. .venv/bin/python scripts/export_openapi.py` |
| Migrations (prod) | GitHub Actions → **Database Migrations** (`workflow_dispatch`) |

### Python formatting (required for CI)

```bash
cd backend && python3 -m black .
cd backend && python3 -m black --check .
```

### MLB strikeouts smoke check (no deploy)

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_strikeouts.py
# Optional: --with-optional, --live (hits DATABASE_URL)
```

---

## Testing

### Backend

```bash
cd backend
source .venv/bin/activate
export PYTHONPATH=.
export DATABASE_URL="postgresql://test_user:test_password@localhost:5432/test_db"
export ENVIRONMENT=testing
export SECRET_KEY=test-secret-key

pytest tests/ -v
```

CI runs Black, flake8 (critical rules), pytest, and verifies committed OpenAPI specs are current when `backend/**` changes.

### Frontend

```bash
cd frontend
npm run lint
npm run type-check
npm run test          # Playwright
```

See [backend/TESTING_GUIDE.md](backend/TESTING_GUIDE.md) for bet-verification-focused manual test cases.

---

## API surface (high level)

Routers are mounted from `backend/app/main.py` and `backend/app/api/`:

| Prefix | Purpose |
|--------|---------|
| `/api/v1/predictions` | Sport prediction feeds |
| `/api/v1/tools` | Utilities (e.g. bet calculator data) |
| `/api/v1/fantasy/analytics` | Fantasy analytics |
| `/api/sleeper` | Sleeper sync |
| `/api/admin/celery` | Worker health, enqueue/run ETL tasks |
| `/api/admin/pipelines` | Pipeline catalog and schedules |
| `/api/admin/yetai-picks` | Auto-pick approval API |
| `/health` | Liveness + dependency diagnostics |

Interactive exploration: **http://localhost:8000/docs** (Swagger) and **/redoc**. Machine-readable specs: [docs/api/README.md](docs/api/README.md).

---

## Background jobs & ETL

Celery app: `backend/app/celery_app.py`. Task modules include:

- `app.tasks.etl_pipeline` — Daily sport pipelines (MLB, NBA, NHL, NFL, …)
- `app.tasks.games_sync` — Game schedule sync
- `app.tasks.auto_pick` — Automated YetAI bet selection (feature-flagged)
- `app.tasks.health` — Worker health probes

**Production operations** (enqueue pipelines, verify data, Redis troubleshooting): [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md) § ETL pipeline runbook.

**Per-sport implementation status:**

| Sport | Doc |
|-------|-----|
| MLB | [backend/docs/MLB_ETL_PARITY.md](backend/docs/MLB_ETL_PARITY.md) |
| NBA | [backend/docs/NBA_ETL_PARITY.md](backend/docs/NBA_ETL_PARITY.md) |
| NHL | [backend/docs/NHL_ETL_PARITY.md](backend/docs/NHL_ETL_PARITY.md) |
| NFL | [backend/docs/NFL_ETL_PARITY.md](backend/docs/NFL_ETL_PARITY.md) |
| WNBA | [backend/docs/WNBA_ETL_PARITY.md](backend/docs/WNBA_ETL_PARITY.md) |
| Cross-sport checklist | [backend/docs/ETL_MIGRATION_STATUS.md](backend/docs/ETL_MIGRATION_STATUS.md) |

---

## Frontend routes (selected)

| Path | Description |
|------|-------------|
| `/` | Landing |
| `/dashboard` | User home |
| `/predictions` | Predictions hub |
| `/predictions/{mlb,nba,nhl,nfl,wnba}` | Sport-specific views |
| `/bets`, `/parlays` | Betting |
| `/odds`, `/leaderboard`, `/performance` | Markets & stats |
| `/fantasy` | Fantasy / Sleeper |
| `/chat` | AI assistant |
| `/admin`, `/admin/pipelines` | Admin & ETL UI |
| `/admin/yetai-picks` | Auto-pick approval (flagged) |
| `/upgrade` | Stripe subscription |

---

## CI/CD and deployment

### Continuous integration

| Workflow | Trigger | Role |
|----------|---------|------|
| [backend-ci-cd.yml](.github/workflows/backend-ci-cd.yml) | `backend/**` on `main` / `develop` | Black, flake8, pytest, OpenAPI drift check |
| [frontend-ci-cd.yml](.github/workflows/frontend-ci-cd.yml) | `frontend/**` | Lint, typecheck, build, Vercel |
| [database-migrate.yml](.github/workflows/database-migrate.yml) | Manual | Alembic upgrade (production/staging) |
| [railway-production-deploy.yml](.github/workflows/railway-production-deploy.yml) | Manual | Deploy API + `celery-worker` to Railway |

Setup secrets and first-time deploy: **[CICD_SETUP.md](CICD_SETUP.md)**.

### Production deploy

1. Merge to `main` after CI passes.
2. **Railway** builds `backend/Dockerfile` for `api.yetai.app`.
3. Deploy **celery-worker** on the same image (see [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md)).
4. **Vercel** hosts the Next.js frontend at `yetai.app`.
5. Optional: run **Railway Production Deploy** from GitHub Actions.

---

## Documentation index

| Document | Contents |
|----------|----------|
| [AGENTS.md](AGENTS.md) | Contributor/agent notes (Black, smoke scripts, OpenAPI export, deploy) |
| [docs/api/README.md](docs/api/README.md) | Committed OpenAPI specs and regeneration |
| [CICD_SETUP.md](CICD_SETUP.md) | GitHub Actions secrets, Vercel/Railway tokens |
| [RAILWAY_DEPLOYMENT.md](RAILWAY_DEPLOYMENT.md) | Docker, health checks, Celery worker, ETL ops |
| [backend/TESTING_GUIDE.md](backend/TESTING_GUIDE.md) | Bet verification test guide |
| [docs/runbooks/auto-yetai-picks.md](docs/runbooks/auto-yetai-picks.md) | Auto-pick rollout and flags |
| [backend/docs/](backend/docs/) | Sport ETL parity and migration status |

---

## Troubleshooting

### PostgreSQL not running

```bash
brew services start postgresql   # macOS
pg_isready
```

### Redis not running / Celery cannot connect

```bash
brew services start redis
redis-cli ping
```

Ensure `REDIS_URL` in `.env` matches your broker. In production, worker and API must use the Railway Redis plugin URL, not `localhost`.

### Port already in use

- API: `8000` — change uvicorn `--port`
- Frontend: `3000` — `npm run dev -- -p 3001`

### Import errors when running scripts

Always set `PYTHONPATH=.` from `backend/` (or use `.venv/bin/python` with that cwd).

### API returns 401 on admin endpoints

Admin Celery/ETL routes require a valid admin JWT (`Authorization: Bearer …`). Obtain from a logged-in admin session (browser `auth_token`).

### OpenAPI CI failure (“specs are stale”)

```bash
cd backend && PYTHONPATH=. .venv/bin/python scripts/export_openapi.py
git add docs/api/
```

---

## Contributing

1. Branch from `main`.
2. Run Black on any touched `backend/**/*.py` files.
3. Regenerate OpenAPI specs when changing routes.
4. Run relevant pytest / frontend checks before opening a PR.
5. See [AGENTS.md](AGENTS.md) for agent workflows.

Issue tracking in this workspace may use **beads** (`bd`) — run `bd ready` for available tasks.

---

## License & support

Private repository. For deployment or infrastructure questions, use the runbooks above and Railway/Vercel dashboards. GitHub Issues: [benyetra/YetAI](https://github.com/benyetra/YetAI/issues).
