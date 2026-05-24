"""Per-day NHL projection accuracy → unified bucket shape.

Only goalies have actuals-ETL coverage; team/player shot and team totals
predictions exist but no actuals writer runs nightly. So this surfaces
just goalie buckets — adding shots/totals when their ETL catches up is
a one-bucket addition.

Buckets:
- Goalie Saves O/U (from saves_line + betting_recommendation parsed for
  the OVER/UNDER side)
- Goalie Saves MAE
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    NHLGoalieActuals,
    NHLGoaliePredictions,
)
from app.services.accuracy_shared import (
    AccuracyBucket,
    assemble,
    mae_bucket,
    ou_call_bucket,
)


def _parse_pick(recommendation: Optional[str]) -> Optional[str]:
    """Extract 'over'/'under' from values like 'OVER 28.5' or 'UNDER 28.5'.

    Returns None for 'PASS' or anything we can't recognize so the bucket
    helper skips the row.
    """
    if not recommendation:
        return None
    head = recommendation.strip().split(" ", 1)[0].lower()
    if head in ("over", "o"):
        return "over"
    if head in ("under", "u"):
        return "under"
    return None


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the NHL accuracy summary for `target_date`."""

    proj = (
        db.query(NHLGoaliePredictions)
        .filter(NHLGoaliePredictions.game_date == target_date)
        .all()
    )
    actuals = (
        db.query(NHLGoalieActuals)
        .filter(NHLGoalieActuals.game_date == target_date)
        .all()
    )
    by_gid = {a.goalie_id: a for a in actuals}

    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_gid.get(p.goalie_id)
        rows.append(
            {
                "goalie_id": p.goalie_id,
                "predicted_saves": p.predicted_saves,
                "saves_line": p.saves_line,
                # ou_call_bucket reads the raw pick string, lowercase it,
                # and accepts over/under/o/u. Pre-parse "OVER 28.5" → "over".
                "betting_pick": _parse_pick(p.betting_recommendation),
                "actual_saves": a.actual_saves if a else None,
            }
        )

    buckets: list[AccuracyBucket] = [
        ou_call_bucket(
            rows,
            line_field="saves_line",
            pick_field="betting_pick",
            actual_field="actual_saves",
            projected_field="predicted_saves",
            label="Goalie Saves O/U",
            key="goalie_saves_ou",
        ),
        mae_bucket(
            rows,
            projected_field="predicted_saves",
            actual_field="actual_saves",
            label="Goalie Saves",
            key="goalie_saves_mae",
            unit_label="saves",
        ),
    ]

    return assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=bool(rows),
    )
