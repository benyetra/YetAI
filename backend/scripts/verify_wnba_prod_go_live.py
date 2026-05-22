#!/usr/bin/env python3
"""Smoke-check WNBA production go-live signals (no auth required for health)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
import urllib.error
import urllib.request

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

HEALTH_URL = "https://api.yetai.app/health"
FRONTEND_URL = "https://yetai.app/predictions/wnba"
WNBA_BEAT_ENTRIES = (
    "wnba-update-pipeline-daily",
    "wnba-update-game-lines-every-30m",
    "wnba-update-injuries-every-2h",
    "wnba-projectors-pregame-hourly",
    "wnba-store-actuals-morning",
    "wnba-totals-accuracy-morning",
    "wnba-spreads-accuracy-morning",
)


def _fetch(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def main() -> int:
    ok = True

    status, body = _fetch(HEALTH_URL)
    print(f"GET {HEALTH_URL} -> {status}")
    if status != 200:
        ok = False
    else:
        data = json.loads(body)
        print(f"  environment: {data.get('environment')}")
        print(f"  database: {data.get('services', {}).get('database')}")
        print(f"  scheduler_running: {data.get('scheduler_running')}")
        odds = data.get("odds_api") or {}
        print(f"  ODDS_API_KEY configured: {odds.get('resolved_key_configured')}")
        if not data.get("services", {}).get("database"):
            ok = False
        if not odds.get("resolved_key_configured"):
            ok = False

    fe_status, _ = _fetch(FRONTEND_URL)
    print(f"GET {FRONTEND_URL} -> {fe_status}")
    if fe_status != 200:
        ok = False

    celery_src = (_BACKEND / "app" / "celery_app.py").read_text(encoding="utf-8")
    missing = [name for name in WNBA_BEAT_ENTRIES if f'"{name}"' not in celery_src]
    if missing:
        print("Missing Celery beat entries:", ", ".join(missing))
        ok = False
    else:
        print(f"Celery beat: all {len(WNBA_BEAT_ENTRIES)} WNBA entries registered")

    print(
        "\nNote: /api/v1/predictions/wnba requires paid auth (403 without token). "
        "Verify in-app after login."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
