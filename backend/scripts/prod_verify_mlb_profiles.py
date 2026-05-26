#!/usr/bin/env python3
"""Production smoke checks for MLB profile snapshot tables (Phase 8)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from app.core.database import SessionLocal
from app.models.mlb_profile_models import (
    MlbBatterProfileSnapshot,
    MlbPitcherProfileSnapshot,
)
from app.services.etl.mlb.profiles.constants import PROFILE_VERSION
from app.services.etl.mlb.profiles.monitoring import snapshot_coverage_report


def main() -> int:
    p = argparse.ArgumentParser(
        description="Verify MLB profile snapshots in production"
    )
    p.add_argument("--json", action="store_true", help="Emit coverage report as JSON")
    p.add_argument("--min-batter-coverage", type=float, default=0.0)
    args = p.parse_args()

    if SessionLocal is None:
        print("ERROR: database not configured")
        return 1

    db = SessionLocal()
    try:
        report = snapshot_coverage_report(db)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            for k, v in report.items():
                print(f"{k}: {v}")

        latest_pitcher = report.get("latest_pitcher_as_of")
        if not latest_pitcher:
            print("WARN: no pitcher snapshots")
            return 1

        latest_pitcher_date = date.fromisoformat(str(latest_pitcher))
        sample = (
            db.query(MlbPitcherProfileSnapshot)
            .filter(
                MlbPitcherProfileSnapshot.as_of_date == latest_pitcher_date,
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

        cov = float(report.get("batter_reliability_coverage_pct", 0))
        if args.min_batter_coverage > 0 and cov < args.min_batter_coverage:
            print(
                f"FAIL: batter reliability coverage {cov}% < {args.min_batter_coverage}%"
            )
            return 1

        print("OK")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
