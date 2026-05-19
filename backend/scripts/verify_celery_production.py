#!/usr/bin/env python3
"""
Production Celery verification (Development-cbd, Development-wwe).

Run on the Railway celery-worker container (needs internal Redis):

  railway service          # link celery-worker
  railway ssh
  cd /app/backend && PYTHONPATH=/app/backend python scripts/verify_celery_production.py

Or one-shot:
  railway ssh -- bash -lc 'cd /app/backend && PYTHONPATH=/app/backend python scripts/verify_celery_production.py'
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    from app.celery_app import celery_app

    print("=== 1. inspect registered (subset) ===")
    registered = celery_app.control.inspect().registered()
    if not registered:
        print("WARN: no workers answered inspect (is celery-worker running?)")
    else:
        for worker, tasks in registered.items():
            print(f"worker: {worker}")
            for name in sorted(tasks):
                if "health" in name or "games_sync" in name or "live_pollers" in name:
                    print(f"  - {name}")

    print("\n=== 2. ping round-trip (cbd) ===")
    ping = celery_app.send_task("app.tasks.health.ping")
    print(f"task_id: {ping.id}")
    ping_result = ping.get(timeout=30)
    print(f"result: {json.dumps(ping_result)}")
    if ping_result.get("status") != "ok":
        print("FAIL: ping status not ok")
        return 1

    print("\n=== 3. sync_games_cache (wwe) ===")
    sync = celery_app.send_task("app.tasks.games_sync.sync_games_cache")
    print(f"task_id: {sync.id}")
    sync_result = sync.get(timeout=180)
    print(f"result: {json.dumps(sync_result, default=str)}")
    if sync_result.get("status") not in ("ok", "skipped"):
        print("FAIL: sync_games_cache did not return ok/skipped")
        return 1
    if sync_result.get("status") == "skipped":
        print("WARN: sync skipped (check ODDS_API_KEY on worker)")

    print("\n=== ALL CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
