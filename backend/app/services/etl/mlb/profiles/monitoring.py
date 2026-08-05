"""Profile coverage and ingest health metrics (Phase 8)."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.mlb_archetype_models import MlbPlayerArchetype, MlbPitcherArchetype
from app.models.mlb_profile_models import (
    MlbBatterProfileSnapshot,
    MlbPitcherProfileSnapshot,
)
from app.services.etl.mlb.profiles.constants import (
    PROFILE_VERSION,
    PROFILE_VERSION_PREV,
)


def snapshot_coverage_report(
    db: Session,
    as_of_date: date | None = None,
    *,
    window: str = "season",
) -> dict[str, Any]:
    """Counts and coverage hints for prod verify / ops dashboards."""
    latest_pitcher = db.query(func.max(MlbPitcherProfileSnapshot.as_of_date)).scalar()
    latest_batter = db.query(func.max(MlbBatterProfileSnapshot.as_of_date)).scalar()
    pitcher_date = as_of_date or latest_pitcher
    batter_date = as_of_date or latest_batter

    n_pitchers = 0
    n_batters = 0
    versions = (PROFILE_VERSION, PROFILE_VERSION_PREV)
    if pitcher_date:
        n_pitchers = (
            db.query(MlbPitcherProfileSnapshot)
            .filter(
                MlbPitcherProfileSnapshot.as_of_date == pitcher_date,
                MlbPitcherProfileSnapshot.profile_version.in_(versions),
                MlbPitcherProfileSnapshot.window == window,
            )
            .count()
        )
    if batter_date:
        n_batters = (
            db.query(MlbBatterProfileSnapshot)
            .filter(
                MlbBatterProfileSnapshot.as_of_date == batter_date,
                MlbBatterProfileSnapshot.profile_version.in_(versions),
                MlbBatterProfileSnapshot.window == window,
            )
            .count()
        )

    reliable_batters = 0
    if batter_date:
        rows = (
            db.query(MlbBatterProfileSnapshot)
            .filter(
                MlbBatterProfileSnapshot.as_of_date == batter_date,
                MlbBatterProfileSnapshot.profile_version.in_(versions),
                MlbBatterProfileSnapshot.window == window,
            )
            .limit(5000)
            .all()
        )
        for row in rows:
            rel = (row.profile or {}).get("reliability_by_pitch") or {}
            top3 = sorted(rel.values(), reverse=True)[:3]
            if top3 and sum(1 for v in top3 if float(v) > 0) >= 2:
                reliable_batters += 1

    batter_coverage_pct = (
        round(100.0 * reliable_batters / n_batters, 1) if n_batters else 0.0
    )

    season = (pitcher_date or date.today()).year
    n_archetypes = (
        db.query(MlbPlayerArchetype).filter(MlbPlayerArchetype.season == season).count()
    )
    n_pitcher_archetypes = (
        db.query(MlbPitcherArchetype)
        .filter(MlbPitcherArchetype.season == season)
        .count()
    )

    return {
        "latest_pitcher_as_of": str(latest_pitcher) if latest_pitcher else None,
        "latest_batter_as_of": str(latest_batter) if latest_batter else None,
        "query_pitcher_date": str(pitcher_date) if pitcher_date else None,
        "query_batter_date": str(batter_date) if batter_date else None,
        "profile_version": PROFILE_VERSION,
        "window": window,
        "n_pitcher_snapshots": n_pitchers,
        "n_batter_snapshots": n_batters,
        "batter_reliability_coverage_pct": batter_coverage_pct,
        "n_archetypes_season": n_archetypes,
        "n_pitcher_archetypes_season": n_pitcher_archetypes,
        "season": season,
    }
