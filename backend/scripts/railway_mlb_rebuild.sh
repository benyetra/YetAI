#!/usr/bin/env bash
# Railway mlb-rebuild-cron start: run profile rebuild and exit.
# Resolves app root when Docker build context is backend/ (correct) or repo root.
set -euo pipefail

APP_ROOT=""
if [[ -f /app/app/celery_app.py ]]; then
  APP_ROOT=/app
elif [[ -f /app/backend/app/celery_app.py ]]; then
  APP_ROOT=/app/backend
else
  echo "railway-mlb-rebuild: cannot find app under /app or /app/backend" >&2
  ls -la /app >&2 || true
  ls -la /app/backend >&2 || true
  exit 1
fi

cd "$APP_ROOT"
export PYTHONPATH="$APP_ROOT"
export MPLBACKEND="${MPLBACKEND:-Agg}"
echo "railway-mlb-rebuild: APP_ROOT=$APP_ROOT" >&2

exec python3 scripts/mlb_rebuild_profiles.py "$@"
