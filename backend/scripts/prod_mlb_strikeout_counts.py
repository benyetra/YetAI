#!/usr/bin/env python3
"""Print prod strikeout training table counts via admin API (no local DATABASE_URL swap).

Usage:
  export YETAI_ADMIN_JWT='...'
  PYTHONPATH=. python3 scripts/prod_mlb_strikeout_counts.py
  PYTHONPATH=. python3 scripts/prod_mlb_strikeout_counts.py --api https://api.yetai.app
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_API = "https://api.yetai.app"


def _get_token(api: str) -> str:
    token = (os.getenv("YETAI_ADMIN_JWT") or os.getenv("ADMIN_TOKEN") or "").strip()
    if token:
        return token
    email = os.getenv("YETAI_ADMIN_EMAIL")
    password = os.getenv("YETAI_ADMIN_PASSWORD")
    if email and password:
        payload = json.dumps(
            {"email_or_username": email, "password": password}
        ).encode()
        req = urllib.request.Request(
            f"{api}/api/auth/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        token = data.get("access_token") or data.get("token")
        if token:
            return token
    raise SystemExit("Set YETAI_ADMIN_JWT or YETAI_ADMIN_EMAIL + YETAI_ADMIN_PASSWORD")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prod MLB strikeout training counts")
    parser.add_argument("--api", default=os.getenv("YETAI_API", DEFAULT_API))
    args = parser.parse_args()

    token = _get_token(args.api)
    url = f"{args.api.rstrip('/')}/api/admin/celery/ml-ops-status"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode()[:500]}") from e

    st = data.get("strikeout_training") or {}
    print("MLB strikeout training (prod DB via API)")
    print(f"  projections: {st.get('projections')}")
    print(f"  actuals:     {st.get('actuals')}")
    print(f"  joined:      {st.get('joined')}")
    print(f"  min joined:  {st.get('min_joined_required')}")
    print(f"  retrain OK:  {st.get('ready_to_retrain')}")

    models = data.get("models") or {}
    for key in ("strikeout_classifier", "hr_model"):
        head = models.get(key)
        if head:
            print(f"  {key}: {head.get('uri')} ({head.get('last_modified')})")

    if len(sys.argv) > 1 and "--json" in sys.argv:
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
