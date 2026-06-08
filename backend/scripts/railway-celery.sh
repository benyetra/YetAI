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

# Fail fast with a clear message if Redis is unreachable (common Railway misconfig).
python3 - <<'PY' || exit 1
import os
import sys

sys.path.insert(0, os.environ.get("PYTHONPATH", "/app"))
try:
    from app.core.redis_broker import pick_redis_url, ping_redis_sync

    url = pick_redis_url()
    ping = ping_redis_sync(url, timeout_s=8.0)
    if ping.get("status") != "ok":
        print(f"railway-celery: Redis ping FAILED: {ping}", file=sys.stderr)
        sys.exit(1)
    print(f"railway-celery: Redis ping OK ({ping.get('target')})", file=sys.stderr)
    raise SystemExit  # skip fallback block below
except SystemExit:
    raise
except Exception:
    pass

url = (
    os.getenv("REDIS_URL")
    or os.getenv("REDIS_PRIVATE_URL")
    or os.getenv("REDIS_PUBLIC_URL")
    or os.getenv("CELERY_BROKER_URL")
)
if not url or "localhost" in url:
    print(
        "railway-celery: REDIS_URL missing or still localhost. "
        "On celery-worker, set REDIS_URL=${{Redis.REDIS_URL}} (or REDIS_PRIVATE_URL) "
        "from the Railway Redis plugin in the same project/environment.",
        file=sys.stderr,
    )
    sys.exit(1)

host_hint = url.split("@")[-1].split("/")[0] if "@" in url else url
print(f"railway-celery: pinging Redis at {host_hint} ...", file=sys.stderr)
try:
    import redis

    client = redis.from_url(url, socket_connect_timeout=8, socket_timeout=8)
    client.ping()
    print("railway-celery: Redis ping OK", file=sys.stderr)
except Exception as exc:
    print(
        f"railway-celery: Redis ping FAILED ({exc}). "
        "Check Redis service is running, linked to celery-worker, and same environment. "
        "Redeploy Redis then redeploy celery-worker.",
        file=sys.stderr,
    )
    sys.exit(1)
PY

# concurrency=2: one slot for long maintenance (profile rebuild, retrain) and one
# for interactive/admin pipeline enqueues without hour-long queue stalls.
exec celery -A app.celery_app worker --beat --loglevel=info --concurrency=2 "$@"
