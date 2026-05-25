"""Per-day MLB projection accuracy → unified bucket shape.

Builds three buckets via the shared `accuracy_shared` helpers:
- Pitcher Ks O/U: FanDuel-line call accuracy + K MAE.
- Projected Hits: success rate for batters projected for ≥1 hit.
- Projected Home Runs: success rate for batters projected for ≥1 HR.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type
from typing import Any

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    ProjectedHits,
    ProjectedHomers,
    StrikeoutActuals,
    StrikeoutProjections,
)
from app.services.accuracy_shared import (
    assemble,
    hit_rate_bucket,
    ou_call_bucket,
)


def _strikeout_accuracy_by_model_version(
    k_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    """Per-model_version O/U buckets when projections carry model_version."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in k_rows:
        version = row.get("model_version")
        if version:
            grouped[str(version)].append(row)
    if not grouped:
        return None
    return {
        version: ou_call_bucket(
            rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_strikeouts",
            projected_field="projected_strikeouts",
            label=f"Pitcher Ks O/U ({version})",
            key="pitcher_ks_ou",
        ).to_dict()
        for version, rows in sorted(grouped.items())
    }


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Fetch the day's MLB projections + actuals, return the bucketed summary."""
    # Strikeouts: merge actuals onto each projection via dict lookup.
    proj_rows = (
        db.query(StrikeoutProjections)
        .filter(StrikeoutProjections.date == target_date)
        .all()
    )
    actuals_by_pid = {
        r.pitcher_id: r
        for r in db.query(StrikeoutActuals)
        .filter(StrikeoutActuals.date == target_date)
        .all()
    }
    k_rows: list[dict[str, Any]] = []
    for p in proj_rows:
        a = actuals_by_pid.get(p.pitcher_id)
        k_rows.append(
            {
                "projected_strikeouts": p.projected_strikeouts,
                "fanduel_line": p.fanduel_line,
                "fanduel_over_under": p.fanduel_over_under,
                "actual_strikeouts": a.actual_strikeouts if a else None,
                "model_version": getattr(p, "model_version", None),
            }
        )

    hits_rows = [
        {"projected_hits": r.projected_hits, "actual_hits": r.actual_hits}
        for r in db.query(ProjectedHits).filter(ProjectedHits.date == target_date).all()
    ]
    homer_rows = [
        {"projected_homers": r.projected_homers, "actual_homers": r.actual_homers}
        for r in db.query(ProjectedHomers)
        .filter(ProjectedHomers.date == target_date)
        .all()
    ]

    buckets = [
        ou_call_bucket(
            k_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_strikeouts",
            projected_field="projected_strikeouts",
            label="Pitcher Ks O/U",
            key="pitcher_ks_ou",
        ),
        hit_rate_bucket(
            hits_rows,
            actual_field="actual_hits",
            projected_field="projected_hits",
            threshold=1,
            label="Projected Hits",
            key="projected_hits",
            secondary="Batters projected for ≥1 hit",
        ),
        hit_rate_bucket(
            homer_rows,
            actual_field="actual_homers",
            projected_field="projected_homers",
            threshold=1,
            label="Projected Home Runs",
            key="projected_homers",
            secondary="Batters projected for ≥1 HR",
        ),
    ]

    out = assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=bool(k_rows or hits_rows or homer_rows),
    )
    by_version = _strikeout_accuracy_by_model_version(k_rows)
    if by_version:
        out["strikeout_by_model_version"] = by_version
    return out
