#!/usr/bin/env bash
# Railway celery-worker start (Development-7l5).
# Resolves app root when Docker build context is backend/ (correct) or repo root (misconfigured).
set -euo pipefail

APP_ROOT=""
if [[ -f /app/app/celery_app.py ]]; then
  APP_ROOT=/app
elif [[ -f /app/backend/app/celery_app.py ]]; then
  APP_ROOT=/app/backend
else
  echo "railway-celery: cannot find app.celery_app under /app or /app/backend" >&2
  ls -la /app >&2 || true
  ls -la /app/backend >&2 || true
  exit 1
fi

cd "$APP_ROOT"
export PYTHONPATH="$APP_ROOT"
echo "railway-celery: APP_ROOT=$APP_ROOT PYTHONPATH=$PYTHONPATH" >&2
exec celery -A app.celery_app worker --beat --loglevel=info --concurrency=1 "$@"
