"""Per-day NFL projection accuracy → unified bucket shape.

NFL projection dates are stored on `game_date` (DateTime). We filter by
calendar day in the server's timezone for simplicity — there's only one
NFL slate per calendar day so timezone edge-cases don't matter much.

Buckets:
- QB Passing Yards O/U (uses `ou_line` + `betting_recommendation`)
- QB Passing Yards MAE
- Kicker FG Made MAE
- Spread ATS (HOME/AWAY edge plays vs market line)
- Game Totals O/U (market_total + recommendation)
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.predictions_models import (
    KickerActuals,
    KickerPredictions,
    NFLSpreadActuals,
    NFLSpreadProjections,
    NFLTotalsActuals,
    NFLTotalsProjections,
    QBActuals,
    QBPredictions,
)
from app.services.accuracy_shared import (
    AccuracyBucket,
    assemble,
    edge_play_bucket,
    mae_bucket,
    ou_call_bucket,
    ou_call_graded_breakdown,
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


def _game_key(row) -> tuple:
    return (row.game_date, row.home_team_name, row.away_team_name)


def _ats_covered(
    recommendation: Optional[str],
    actual_margin: int | None,
    market_spread_home: float | None,
) -> bool | None:
    """Return True/False if pick covered; None for pushes or no-play."""
    if not recommendation or recommendation == "NO_PLAY" or market_spread_home is None:
        return None
    if actual_margin is None:
        return None
    threshold = -market_spread_home
    if actual_margin == threshold:
        return None
    if recommendation == "HOME":
        return actual_margin > threshold
    if recommendation == "AWAY":
        return actual_margin < threshold
    return None


def _merge_actuals_spread(projections, actuals) -> list[dict[str, Any]]:
    by_key = {_game_key(a): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in projections:
        a = by_key.get(_game_key(p))
        actual_margin = a.actual_margin if a else None
        out.append(
            {
                "projected_margin": p.projected_margin,
                "market_spread_home": p.market_spread_home,
                "recommendation": p.recommendation,
                "actual_margin": actual_margin,
                "spread_correct": _ats_covered(
                    p.recommendation, actual_margin, p.market_spread_home
                ),
            }
        )
    return out


def _merge_actuals_totals(projections, actuals) -> list[dict[str, Any]]:
    by_key = {_game_key(a): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in projections:
        a = by_key.get(_game_key(p))
        out.append(
            {
                "projected_total": p.projected_total,
                "market_total": p.market_total,
                "recommendation": p.recommendation,
                "actual_total": a.actual_total if a else None,
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

    spread_proj = (
        db.query(NFLSpreadProjections)
        .filter(NFLSpreadProjections.game_date == target_date)
        .all()
    )
    spread_actuals = (
        db.query(NFLSpreadActuals)
        .filter(NFLSpreadActuals.game_date == target_date)
        .all()
    )
    spread_rows = _merge_actuals_spread(spread_proj, spread_actuals)

    totals_proj = (
        db.query(NFLTotalsProjections)
        .filter(NFLTotalsProjections.game_date == target_date)
        .all()
    )
    totals_actuals = (
        db.query(NFLTotalsActuals)
        .filter(NFLTotalsActuals.game_date == target_date)
        .all()
    )
    totals_rows = _merge_actuals_totals(totals_proj, totals_actuals)

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
        edge_play_bucket(
            spread_rows,
            pick_field="recommendation",
            correct_field="spread_correct",
            label="Spread ATS",
            key="spread_ats",
            secondary="Spread edge plays vs market line",
        ),
        ou_call_bucket(
            totals_rows,
            line_field="market_total",
            pick_field="recommendation",
            actual_field="actual_total",
            projected_field="projected_total",
            label="Game Totals O/U",
            key="totals_ou",
        ),
    ]

    return assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=bool(qb_rows or k_rows or spread_rows or totals_rows),
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


def season_overview_diagnostics(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, Any]:
    """Structured counts for admin/debug — QB pass yards O/U only (overview scope)."""
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
    bd = ou_call_graded_breakdown(
        qb_rows,
        line_field="ou_line",
        pick_field="betting_recommendation",
        actual_field="actual_passing_yards",
    )
    c, t = bd["graded_correct"], bd["graded_total"]
    return {
        "sport": "nfl",
        "date_bounds": {"start": start.isoformat(), "end": end.isoformat()},
        "overview": overview_item_from_totals(
            sport="nfl", label="NFL", correct=c, total=t
        ),
        "parts": [
            {
                "key": "qb_passing_ou",
                "label": "QB Pass Yds O/U",
                "kind": "ou",
                "breakdown": bd,
                "graded_correct": c,
                "graded_total": t,
            }
        ],
    }
