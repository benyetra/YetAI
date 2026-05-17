#!/bin/bash
# Bulletproof Celery worker entrypoint for Railway.
#
# Why this exists: Railway's per-service start-command override runs from /,
# not the Dockerfile's WORKDIR. PYTHONPATH=/app set in the Dockerfile should
# fix it, but in practice on Railway it doesn't (the env var isn't preserved
# into the start-command's exec context). This script forces the cd before
# launching celery so the import resolution works regardless.
set -e
cd /app
exec celery -A app.celery_app worker --beat --loglevel=info --concurrency=1
