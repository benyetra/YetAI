#!/usr/bin/env python3
"""Production smoke checks for MLB profile snapshot tables."""

from __future__ import annotations

import sys
from datetime import date

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.mlb_profile_models import (
    MlbBatterProfileSnapshot,
    MlbPitcherProfileSnapshot,
)
from app.services.etl.mlb.profiles.constants import PROFILE_VERSION


def main() -> int:
    if SessionLocal is None:
        print("ERROR: database not configured")
        return 1

    db = SessionLocal()
    try:
        latest_pitcher = db.query(
            func.max(MlbPitcherProfileSnapshot.as_of_date)
        ).scalar()
        latest_batter = db.query(func.max(MlbBatterProfileSnapshot.as_of_date)).scalar()
        print(f"latest pitcher as_of_date: {latest_pitcher}")
        print(f"latest batter as_of_date: {latest_batter}")

        if not latest_pitcher:
            print("WARN: no pitcher snapshots")
            return 1

        n_pitchers = (
            db.query(MlbPitcherProfileSnapshot)
            .filter(
                MlbPitcherProfileSnapshot.as_of_date == latest_pitcher,
                MlbPitcherProfileSnapshot.profile_version == PROFILE_VERSION,
            )
            .count()
        )
        n_batters = (
            db.query(MlbBatterProfileSnapshot)
            .filter(
                MlbBatterProfileSnapshot.as_of_date == latest_batter,
                MlbBatterProfileSnapshot.profile_version == PROFILE_VERSION,
            )
            .count()
        )
        print(f"snapshots @ pitcher date: pitchers={n_pitchers} batters={n_batters}")

        sample = (
            db.query(MlbPitcherProfileSnapshot)
            .filter(
                MlbPitcherProfileSnapshot.as_of_date == latest_pitcher,
                MlbPitcherProfileSnapshot.window == "season",
            )
            .first()
        )
        if sample and sample.profile:
            usage = sample.profile.get("usage", {})
            total = sum(usage.values()) if usage else 0.0
            print(f"sample pitcher {sample.pitcher_id} usage sum={total:.3f}")
            if usage and not (0.95 <= total <= 1.05):
                print("WARN: usage does not sum ~1.0")
                return 1

        print("OK")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
