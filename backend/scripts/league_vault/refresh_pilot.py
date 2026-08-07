#!/usr/bin/env python3
"""
Manually refresh League Vault public sites (re-ingest + force recompute).

Usage (from backend/):
  PYTHONPATH=. .venv/bin/python scripts/league_vault/refresh_pilot.py
  PYTHONPATH=. .venv/bin/python scripts/league_vault/refresh_pilot.py --slug mikes-hard
  PYTHONPATH=. .venv/bin/python scripts/league_vault/refresh_pilot.py --compute-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", help="Refresh a single site slug")
    parser.add_argument(
        "--compute-only",
        action="store_true",
        help="Skip platform re-ingest; only force all-play + records",
    )
    args = parser.parse_args()

    from app.core.database import SessionLocal
    from app.models.league_vault_models import LvSite
    from app.services.league_vault.sync.refresh import (
        refresh_all_public_sites,
        refresh_site,
    )

    if SessionLocal is None:
        print("ERROR: database not configured", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        if args.slug:
            site = (
                db.query(LvSite)
                .filter(LvSite.slug == args.slug, LvSite.is_public.is_(True))
                .one_or_none()
            )
            if site is None:
                print(f"ERROR: public site not found: {args.slug}", file=sys.stderr)
                return 1
            summary = refresh_site(
                db,
                site,
                reingest=not args.compute_only,
                force_compute=True,
            )
        else:
            summary = refresh_all_public_sites(
                db,
                reingest=not args.compute_only,
                force_compute=True,
            )
        print(json.dumps(summary, indent=2, default=str))
        return 0 if not summary.get("errors") else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
