"""Per-day WNBA projection accuracy → unified bucket shape.

WNBA only has game-level projections (no per-player props). We grade:
- Game Totals O/U (uses `market_total` + `recommendation` side)
- Game Totals MAE (projected_total vs actual_total)
- Spread MAE (projected_margin vs actual_margin)

The `recommendation` column on WNBATotalsProjections looks like
"OVER" / "UNDER" / "PASS"; we lowercase the first token and feed it to
the shared O/U helper which handles 'pass' by skipping the row.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    WNBASpreadActuals,
    WNBASpreadProjections,
    WNBATotalsActuals,
    WNBATotalsProjections,
)
from app.services.accuracy_shared import (
    AccuracyBucket,
    assemble,
    mae_bucket,
    ou_call_bucket,
)


def _pick(recommendation: Optional[str]) -> Optional[str]:
    if not recommendation:
        return None
    head = recommendation.strip().split(" ", 1)[0].lower()
    return head if head in ("over", "under") else None


def _game_key(row) -> tuple:
    return (row.game_date, row.home_team_name, row.away_team_name)


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the WNBA accuracy summary for `target_date`."""

    totals_proj = (
        db.query(WNBATotalsProjections)
        .filter(WNBATotalsProjections.game_date == target_date)
        .all()
    )
    totals_actuals = (
        db.query(WNBATotalsActuals)
        .filter(WNBATotalsActuals.game_date == target_date)
        .all()
    )
    totals_by_key = {_game_key(a): a for a in totals_actuals}

    totals_rows: list[dict[str, Any]] = []
    for p in totals_proj:
        a = totals_by_key.get(_game_key(p))
        totals_rows.append(
            {
                "projected_total": p.projected_total,
                "market_total": p.market_total,
                "recommendation": _pick(p.recommendation),
                "actual_total": a.actual_total if a else None,
            }
        )

    spread_proj = (
        db.query(WNBASpreadProjections)
        .filter(WNBASpreadProjections.game_date == target_date)
        .all()
    )
    spread_actuals = (
        db.query(WNBASpreadActuals)
        .filter(WNBASpreadActuals.game_date == target_date)
        .all()
    )
    spread_by_key = {_game_key(a): a for a in spread_actuals}

    spread_rows: list[dict[str, Any]] = []
    for p in spread_proj:
        a = spread_by_key.get(_game_key(p))
        spread_rows.append(
            {
                "projected_margin": p.projected_margin,
                "actual_margin": a.actual_margin if a else None,
            }
        )

    buckets: list[AccuracyBucket] = [
        ou_call_bucket(
            totals_rows,
            line_field="market_total",
            pick_field="recommendation",
            actual_field="actual_total",
            projected_field="projected_total",
            label="Game Totals O/U",
            key="totals_ou",
        ),
        mae_bucket(
            totals_rows,
            projected_field="projected_total",
            actual_field="actual_total",
            label="Game Totals",
            key="totals_mae",
            unit_label="pts",
        ),
        mae_bucket(
            spread_rows,
            projected_field="projected_margin",
            actual_field="actual_margin",
            label="Spread Margin",
            key="spread_mae",
            unit_label="pts",
        ),
    ]

    return assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=bool(totals_rows or spread_rows),
    )
