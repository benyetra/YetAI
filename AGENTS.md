# YetAI agent notes

## Python formatting (required)

Backend CI enforces **Black** from `backend/`:

```bash
cd backend && python3 -m black .
cd backend && python3 -m black --check .
```

Before committing any change under `backend/`, run Black on touched files (or the whole tree) and include formatted files in the commit. See `.cursor/rules/yetai-python-black.mdc`.

## MLB Monte Carlo smoke (no deploy)

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_monte_carlo.py
```

Game pipeline runs MC by default (`MLB_MC_ENABLED=1`). See `backend/docs/MLB_MONTE_CARLO.md`.

## MLB strikeouts quick check (no deploy)

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_strikeouts.py
```

Optional: `--with-optional` (sklearn tests), `--live` (full `strikeouts.run()` against `DATABASE_URL`).

## MLB matchup profiles (no deploy)

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_statcast_backfill.py --season 2024 --month 5
PYTHONPATH=. .venv/bin/python scripts/mlb_rebuild_profiles.py --as-of 2024-10-01
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_profiles.py
```

See `backend/docs/MLB_MATCHUP_PROFILES.md`.

## NFL backtest (no deploy)

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/nfl_backtest.py --quick
```

## OpenAPI / Swagger

Regenerate committed specs after API route changes:

```bash
cd backend && PYTHONPATH=. .venv/bin/python scripts/export_openapi.py
```

Outputs: `docs/api/openapi-public.json` (agents/apps), `docs/api/openapi-admin.json`, `docs/api/openapi.json`. Live UI: `/docs`, `/redoc`. See `docs/api/README.md`.

## Deployment

Production deploy: GitHub Actions workflow **Railway Production Deploy** (`workflow_dispatch` or push to `main` after CI passes). Deploys API and celery-worker.
