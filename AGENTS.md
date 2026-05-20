# YetAI agent notes

## Python formatting (required)

Backend CI enforces **Black** from `backend/`:

```bash
cd backend && python3 -m black .
cd backend && python3 -m black --check .
```

Before committing any change under `backend/`, run Black on touched files (or the whole tree) and include formatted files in the commit. See `.cursor/rules/yetai-python-black.mdc`.

## MLB strikeouts quick check (no deploy)

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_strikeouts.py
```

Optional: `--with-optional` (sklearn tests), `--live` (full `strikeouts.run()` against `DATABASE_URL`).

## Deployment

Production deploy: GitHub Actions workflow **Railway Production Deploy** (`workflow_dispatch` or push to `main` after CI passes). Deploys API and celery-worker.
