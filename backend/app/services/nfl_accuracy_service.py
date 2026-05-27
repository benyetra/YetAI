"""Per-day NFL projection accuracy → unified bucket shape.

NFL projection dates are stored on `game_date` (DateTime). We filter by
calendar day in the server's timezone for simplicity — there's only one
NFL slate per calendar day so timezone edge-cases don't matter much.

Buckets:
- QB Passing Yards O/U (uses `ou_line` + `betting_recommendation`)
- QB Passing Yards MAE
- Kicker FG Made MAE
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.predictions_models import (
    KickerActuals,
    KickerPredictions,
    QBActuals,
    QBPredictions,
)
from app.services.accuracy_shared import (
    AccuracyBucket,
    assemble,
    mae_bucket,
    ou_call_bucket,
    ou_call_graded_counts,
    overview_item_from_totals,
)


def _game_date_only(value: Any) -> date_type:
    if value is None:
        raise ValueError("missing game_date")
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, date_type):
        return value
    raise TypeError(f"unsupported date type {type(value)}")


def _merge_actuals_qb_range(
    projections: list[Any], actuals: list[Any]
) -> list[dict[str, Any]]:
    by_key = {(a.qb_player_id, _game_date_only(a.game_date)): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in projections:
        key = (p.qb_player_id, _game_date_only(p.game_date))
        a = by_key.get(key)
        out.append(
            {
                "qb_player_id": p.qb_player_id,
                "predicted_passing_yards": p.predicted_passing_yards,
                "ou_line": p.ou_line,
                "betting_recommendation": p.betting_recommendation,
                "actual_passing_yards": a.actual_passing_yards if a else None,
            }
        )
    return out


def _merge_actuals_qb(projections, actuals) -> list[dict[str, Any]]:
    by_pid = {a.qb_player_id: a for a in actuals}
    out = []
    for p in projections:
        a = by_pid.get(p.qb_player_id)
        out.append(
            {
                "qb_player_id": p.qb_player_id,
                "predicted_passing_yards": p.predicted_passing_yards,
                "ou_line": p.ou_line,
                "betting_recommendation": p.betting_recommendation,
                "actual_passing_yards": a.actual_passing_yards if a else None,
            }
        )
    return out


def _merge_actuals_kicker(projections, actuals) -> list[dict[str, Any]]:
    by_pid = {a.kicker_id: a for a in actuals}
    out = []
    for p in projections:
        a = by_pid.get(p.kicker_player_id)
        out.append(
            {
                "kicker_id": p.kicker_player_id,
                "predicted_fg_made": p.predicted_fg_made,
                "actual_field_goals_made": a.actual_field_goals_made if a else None,
            }
        )
    return out


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the NFL accuracy summary for `target_date`."""

    qb_proj = (
        db.query(QBPredictions)
        .filter(func.date(QBPredictions.game_date) == target_date)
        .all()
    )
    qb_actuals = (
        db.query(QBActuals).filter(func.date(QBActuals.game_date) == target_date).all()
    )
    qb_rows = _merge_actuals_qb(qb_proj, qb_actuals)

    k_proj = (
        db.query(KickerPredictions)
        .filter(func.date(KickerPredictions.game_date) == target_date)
        .all()
    )
    k_actuals = db.query(KickerActuals).filter(KickerActuals.date == target_date).all()
    k_rows = _merge_actuals_kicker(k_proj, k_actuals)

    buckets: list[AccuracyBucket] = [
        ou_call_bucket(
            qb_rows,
            line_field="ou_line",
            pick_field="betting_recommendation",
            actual_field="actual_passing_yards",
            projected_field="predicted_passing_yards",
            label="QB Pass Yds O/U",
            key="qb_passing_ou",
        ),
        mae_bucket(
            qb_rows,
            projected_field="predicted_passing_yards",
            actual_field="actual_passing_yards",
            label="QB Passing Yds",
            key="qb_passing_mae",
            unit_label="yds",
        ),
        mae_bucket(
            k_rows,
            projected_field="predicted_fg_made",
            actual_field="actual_field_goals_made",
            label="Kicker FG Made",
            key="kicker_fg_mae",
            unit_label="FG",
        ),
    ]

    return assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=bool(qb_rows or k_rows),
    )


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Window NFL accuracy — QB passing yards O/U only (kicker rows are MAE-only)."""
    qb_proj = (
        db.query(QBPredictions)
        .filter(
            func.date(QBPredictions.game_date) >= start,
            func.date(QBPredictions.game_date) <= end,
        )
        .all()
    )
    qb_actuals = (
        db.query(QBActuals)
        .filter(
            func.date(QBActuals.game_date) >= start,
            func.date(QBActuals.game_date) <= end,
        )
        .all()
    )
    qb_rows = _merge_actuals_qb_range(qb_proj, qb_actuals)
    correct, total = ou_call_graded_counts(
        qb_rows,
        line_field="ou_line",
        pick_field="betting_recommendation",
        actual_field="actual_passing_yards",
    )
    return overview_item_from_totals(
        sport="nfl", label="NFL", correct=correct, total=total
    )
