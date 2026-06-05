# YetAI agent notes

## Pre-commit quality gates (required)

Before **commit or push**, run formatters and tests for every area you changed; **fix failures and re-run until green**. See `.cursor/rules/yetai-pre-commit-gates.mdc`.

**Backend:** `cd backend && python3 -m black . && python3 -m black --check . && PYTHONPATH=. .venv/bin/python -m pytest -q`

**Frontend:** `cd frontend && npm run lint && npm run type-check && npm run test:ci`

Regenerate `docs/api/openapi*.json` after API route changes (`scripts/export_openapi.py`).

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

## MLB backtest historical odds (Odds API credits)

Prefetch dates into `scripts/mlb_backtest_cache.db` (~20 credits/date for h2h+totals):

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_backfill_historical_odds.py \
  --from-csv scripts/mlb_backtest_results/backtest_<run>_YYYY-MM-DD.csv --max-dates 20 --dry-run
```

Set `ODDS_API_KEY` in `.env.production` (paid plan). Then rerun `scripts/mlb_backtest.py` **without** `--skip-odds`.

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

## Team logos (design UI)

MLB/NFL SVGs live under `frontend/public/team-logos/{mlb,nfl}/`. Other leagues are synced from ESPN’s public teams API:

```bash
cd backend && PYTHONPATH=. python3 scripts/download_espn_team_logos.py
```

Refreshes `frontend/public/team-logos/{nba,wnba,nhl,epl,mls,ucl,ncaaf,ncaab}/` and `frontend/src/lib/team-logo-registry.generated.ts`.

Team primary/secondary colors (same ESPN source):

```bash
cd backend && PYTHONPATH=. python3 scripts/sync_team_colors.py
```

Refreshes `frontend/src/lib/team-colors-registry.generated.ts`. UI lookups: `frontend/src/lib/team-colors.ts`.

## Railway production deploy

**Railway Production Deploy** runs only on `backend/**`, `railway.json`, or workflow changes — not on frontend-only commits. Use **workflow_dispatch** if you need to redeploy API after a frontend-only push.

## OpenAPI / Swagger

Regenerate committed specs after API route changes:

```bash
cd backend && PYTHONPATH=. .venv/bin/python scripts/export_openapi.py
```

Outputs: `docs/api/openapi-public.json` (agents/apps), `docs/api/openapi-admin.json`, `docs/api/openapi.json`. Live UI: `/docs`, `/redoc`. See `docs/api/README.md`.

## Deployment

Production deploy: GitHub Actions workflow **Railway Production Deploy** (`workflow_dispatch` or push to `main` after CI passes). Deploys API and celery-worker.
