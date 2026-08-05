#!/usr/bin/env python3
"""Assign pitcher archetypes from profile snapshots (usage + FB velo)."""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Assign MLB pitcher archetypes from snapshots"
    )
    p.add_argument("--season", type=int, default=date.today().year)
    p.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD snapshot date")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and print counts without writing",
    )
    args = p.parse_args()

    from sqlalchemy import func

    from app.core.database import SessionLocal
    from app.models.mlb_profile_models import MlbPitcherProfileSnapshot
    from app.services.etl.mlb.profiles.constants import (
        PROFILE_VERSION,
        PROFILE_VERSION_PREV,
    )
    from app.services.etl.mlb.profiles.pitcher_archetypes import (
        assign_pitcher_archetype,
        classify_pitcher_archetype,
    )

    if SessionLocal is None:
        logger.error("DATABASE_URL not configured")
        return 1

    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    db = SessionLocal()
    try:
        versions = (PROFILE_VERSION, PROFILE_VERSION_PREV)
        q = db.query(MlbPitcherProfileSnapshot).filter(
            MlbPitcherProfileSnapshot.window == "season",
            MlbPitcherProfileSnapshot.profile_version.in_(versions),
        )
        if as_of is not None:
            q = q.filter(MlbPitcherProfileSnapshot.as_of_date == as_of)
        else:
            # Prefer latest as_of that has any season-window rows for this season year.
            max_as_of = (
                db.query(func.max(MlbPitcherProfileSnapshot.as_of_date))
                .filter(
                    MlbPitcherProfileSnapshot.window == "season",
                    MlbPitcherProfileSnapshot.profile_version.in_(versions),
                    func.extract("year", MlbPitcherProfileSnapshot.as_of_date)
                    == args.season,
                )
                .scalar()
            )
            if max_as_of is None:
                max_as_of = (
                    db.query(func.max(MlbPitcherProfileSnapshot.as_of_date))
                    .filter(
                        MlbPitcherProfileSnapshot.window == "season",
                        MlbPitcherProfileSnapshot.profile_version.in_(versions),
                    )
                    .scalar()
                )
            if max_as_of is None:
                logger.error("No pitcher profile snapshots found")
                return 1
            as_of = max_as_of
            q = q.filter(MlbPitcherProfileSnapshot.as_of_date == as_of)

        # Prefer current PROFILE_VERSION when both exist for same pitcher.
        rows = q.order_by(
            MlbPitcherProfileSnapshot.pitcher_id,
            MlbPitcherProfileSnapshot.profile_version.desc(),
        ).all()

        seen: set[int] = set()
        counts: Counter[str] = Counter()
        for row in rows:
            if row.pitcher_id in seen:
                continue
            seen.add(row.pitcher_id)
            prof = row.profile or {}
            usage = prof.get("usage") or {}
            avg_fb = prof.get("avg_fb_velo")
            if avg_fb is None and prof.get("velo_by_pitch"):
                vb = prof["velo_by_pitch"]
                fb = [vb[k] for k in ("FF", "SI", "FC") if k in vb]
                avg_fb = sum(fb) / len(fb) if fb else None
            if usage and row.n_pitches >= 50:
                aid = classify_pitcher_archetype(usage, avg_fb, row.hand)
            else:
                aid = "mixed_arsenal"
            counts[aid] += 1
            if not args.dry_run:
                assign_pitcher_archetype(
                    db,
                    row.pitcher_id,
                    aid,
                    args.season,
                    n_pitches=row.n_pitches,
                    avg_fb_velo=float(avg_fb) if avg_fb is not None else None,
                )

        if not args.dry_run:
            db.commit()
        logger.info(
            "as_of=%s season=%s pitchers=%s dry_run=%s counts=%s",
            as_of,
            args.season,
            len(seen),
            args.dry_run,
            dict(counts),
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
