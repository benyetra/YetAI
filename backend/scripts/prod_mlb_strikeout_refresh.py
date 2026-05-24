#!/usr/bin/env python3
"""Refresh MLB strikeout board + archive today's K projections (production).

Requires DATABASE_URL (e.g. from resolve_railway_database_url.py on CI).

Usage (from backend/):
  export DATABASE_URL="$(python3 scripts/resolve_railway_database_url.py)"
  PYTHONPATH=. python3 scripts/prod_mlb_strikeout_refresh.py
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    from app.services.etl.mlb._db import close_session, init_session
    from app.services.etl.mlb.daily_projection_update import (
        run_store_strikeout_projections,
    )
    from app.services.etl.mlb.strikeouts import run as run_strikeouts

    print("=== mlb.strikeouts (pred_pitcher) ===")
    k_result = run_strikeouts()
    print(json.dumps(k_result, indent=2, default=str))
    if k_result.get("status") != "ok":
        return 1

    print("=== store_strikeout_projections ===")
    init_session()
    try:
        archive = run_store_strikeout_projections()
    finally:
        close_session()
    print(json.dumps(archive, indent=2, default=str))
    if archive.get("status") != "ok":
        return 1

    print("PASS: strikeout refresh complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
