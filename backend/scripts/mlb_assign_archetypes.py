#!/usr/bin/env python3
"""Assign batter archetypes from profile snapshots (Phase 6 offline job)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Assign MLB batter archetypes from snapshots"
    )
    p.add_argument("--season", type=int, default=date.today().year)
    p.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD snapshot date")
    args = p.parse_args()

    from app.core.database import SessionLocal
    from app.models.mlb_profile_models import MlbBatterProfileSnapshot
    from app.services.etl.mlb.profiles.archetypes import (
        assign_archetype,
        classify_archetype_from_whiff,
    )
    from app.services.etl.mlb.profiles.constants import PROFILE_VERSION

    if SessionLocal is None:
        logger.error("DATABASE_URL not configured")
        return 1

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    db = SessionLocal()
    try:
        rows = (
            db.query(MlbBatterProfileSnapshot)
            .filter(
                MlbBatterProfileSnapshot.as_of_date == as_of,
                MlbBatterProfileSnapshot.profile_version == PROFILE_VERSION,
                MlbBatterProfileSnapshot.window == "season",
            )
            .all()
        )
        seen: set[int] = set()
        for row in rows:
            if row.batter_id in seen:
                continue
            seen.add(row.batter_id)
            whiff = (row.profile or {}).get("whiff_by_pitch") or {}
            aid = classify_archetype_from_whiff(whiff, row.vs_hand)
            assign_archetype(db, row.batter_id, aid, args.season, row.n_pitches)
        db.commit()
        logger.info("assigned %s archetypes for season %s", len(seen), args.season)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
