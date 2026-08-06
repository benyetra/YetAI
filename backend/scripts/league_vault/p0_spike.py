#!/usr/bin/env python3
"""
League Vault Phase 0 spike — verify env gates and DB connectivity.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402


def main() -> int:
    env_path = BACKEND / ".env.leaguevault.local"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded {env_path}")
    else:
        print(f"No {env_path} — using process env")

    gates = {
        "DATABASE_URL": bool(os.environ.get("DATABASE_URL")),
        "SLEEPER_LEAGUE_ID": bool(os.environ.get("SLEEPER_LEAGUE_ID")),
        "ESPN_LEAGUE_ID": bool(os.environ.get("ESPN_LEAGUE_ID")),
        "ESPN_S2": bool(os.environ.get("ESPN_S2") or os.environ.get("ESPN_S2_COOKIE")),
        "ESPN_SWID": bool(os.environ.get("ESPN_SWID") or os.environ.get("SWID")),
    }
    print("P0 gates:")
    for key, ok in gates.items():
        print(f"  {'✓' if ok else '✗'} {key}")

    try:
        from app.core.database import SessionLocal, check_db_connection

        if SessionLocal is None:
            print("SessionLocal unavailable (no DATABASE_URL)")
            return 1
        if check_db_connection():
            print("DB connection: OK")
        else:
            print("DB connection: FAILED")
            return 1
    except Exception as exc:
        print(f"DB check error: {exc}")
        return 1

    print("P0 spike complete — run sync_pilot.py for ingest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
