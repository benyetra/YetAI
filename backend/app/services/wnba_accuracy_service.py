"""Per-day WNBA projection accuracy → unified bucket shape.

Six buckets:

- Game Totals O/U (market_total + recommendation)
- Game Totals MAE
- Spread Margin MAE
- Points O/U (per-player; uses market_line + recommendation)
- Assists O/U (per-player)
- Rebounds O/U (per-player)

The per-player projections + actuals tables are populated by the
existing `generate_*_predictions.py` and `calculate_prediction_accuracy.py`
ETLs. This service just surfaces them in the accuracy summary.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    WNBAAssistsActuals,
    WNBAAssistsProjections,
    WNBAPointsActuals,
    WNBAPointsProjections,
    WNBAReboundsActuals,
    WNBAReboundsProjections,
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
    ou_call_graded_breakdown,
    ou_call_graded_counts,
    overview_item_from_totals,
)


def _pick(recommendation: Optional[str]) -> Optional[str]:
    if not recommendation:
        return None
    head = recommendation.strip().split(" ", 1)[0].lower()
    return head if head in ("over", "under") else None


def _game_key(row) -> tuple:
    return (row.game_date, row.home_team_name, row.away_team_name)


def _player_prop_rows_range(
    db: Session,
    start: date_type,
    end: date_type,
    projections_cls,
    actuals_cls,
    *,
    proj_field: str,
    actual_field: str,
) -> list[dict[str, Any]]:
    proj = (
        db.query(projections_cls)
        .filter(projections_cls.date >= start, projections_cls.date <= end)
        .all()
    )
    actuals = (
        db.query(actuals_cls)
        .filter(actuals_cls.date >= start, actuals_cls.date <= end)
        .all()
    )
    by_key = {(a.player_id, a.date): a for a in actuals}
    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_key.get((p.player_id, p.date))
        rows.append(
            {
                proj_field: getattr(p, proj_field),
                "market_line": p.market_line,
                "recommendation": _pick(p.recommendation),
                actual_field: getattr(a, actual_field) if a else None,
            }
        )
    return rows


def _player_prop_rows(
    db: Session,
    target_date: date_type,
    projections_cls,
    actuals_cls,
    *,
    proj_field: str,
    actual_field: str,
) -> list[dict[str, Any]]:
    """Build per-player rows for a points/assists/rebounds prop.

    Both projection and actuals tables have a `date` column (not `game_date`)
    via the WNBA _make_prop_projection / _make_prop_actuals factory.
    """
    proj = db.query(projections_cls).filter(projections_cls.date == target_date).all()
    actuals = db.query(actuals_cls).filter(actuals_cls.date == target_date).all()
    by_pid = {a.player_id: a for a in actuals}

    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_pid.get(p.player_id)
        rows.append(
            {
                proj_field: getattr(p, proj_field),
                "market_line": p.market_line,
                "recommendation": _pick(p.recommendation),
                actual_field: getattr(a, actual_field) if a else None,
            }
        )
    return rows


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the WNBA accuracy summary for `target_date`."""

    # --- Game totals ----------------------------------------------------
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

    # --- Spread ---------------------------------------------------------
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

    # --- Per-player props ----------------------------------------------
    points_rows = _player_prop_rows(
        db,
        target_date,
        WNBAPointsProjections,
        WNBAPointsActuals,
        proj_field="projected_points",
        actual_field="actual_points",
    )
    assists_rows = _player_prop_rows(
        db,
        target_date,
        WNBAAssistsProjections,
        WNBAAssistsActuals,
        proj_field="projected_assists",
        actual_field="actual_assists",
    )
    rebounds_rows = _player_prop_rows(
        db,
        target_date,
        WNBAReboundsProjections,
        WNBAReboundsActuals,
        proj_field="projected_rebounds",
        actual_field="actual_rebounds",
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
        ou_call_bucket(
            points_rows,
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_points",
            projected_field="projected_points",
            label="Player Points O/U",
            key="player_points_ou",
        ),
        ou_call_bucket(
            assists_rows,
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_assists",
            projected_field="projected_assists",
            label="Player Assists O/U",
            key="player_assists_ou",
        ),
        ou_call_bucket(
            rebounds_rows,
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_rebounds",
            projected_field="projected_rebounds",
            label="Player Rebounds O/U",
            key="player_rebounds_ou",
        ),
    ]

    available = bool(
        totals_rows or spread_rows or points_rows or assists_rows or rebounds_rows
    )
    return assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=available,
    )


def _wnba_season_overview_row_sets(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, list[dict[str, Any]]]:
    """Row dicts for the four WNBA overview O/U sources."""
    totals_proj = (
        db.query(WNBATotalsProjections)
        .filter(
            WNBATotalsProjections.game_date >= start,
            WNBATotalsProjections.game_date <= end,
        )
        .all()
    )
    totals_actuals = (
        db.query(WNBATotalsActuals)
        .filter(
            WNBATotalsActuals.game_date >= start,
            WNBATotalsActuals.game_date <= end,
        )
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

    points_rows = _player_prop_rows_range(
        db,
        start,
        end,
        WNBAPointsProjections,
        WNBAPointsActuals,
        proj_field="projected_points",
        actual_field="actual_points",
    )
    assists_rows = _player_prop_rows_range(
        db,
        start,
        end,
        WNBAAssistsProjections,
        WNBAAssistsActuals,
        proj_field="projected_assists",
        actual_field="actual_assists",
    )
    rebounds_rows = _player_prop_rows_range(
        db,
        start,
        end,
        WNBAReboundsProjections,
        WNBAReboundsActuals,
        proj_field="projected_rebounds",
        actual_field="actual_rebounds",
    )
    return {
        "totals": totals_rows,
        "points": points_rows,
        "assists": assists_rows,
        "rebounds": rebounds_rows,
    }


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Window WNBA accuracy — game totals + player props O/U (spread is MAE-only)."""
    r = _wnba_season_overview_row_sets(db, start=start, end=end)
    parts = [
        ou_call_graded_counts(
            r["totals"],
            line_field="market_total",
            pick_field="recommendation",
            actual_field="actual_total",
        ),
        ou_call_graded_counts(
            r["points"],
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_points",
        ),
        ou_call_graded_counts(
            r["assists"],
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_assists",
        ),
        ou_call_graded_counts(
            r["rebounds"],
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_rebounds",
        ),
    ]
    correct = sum(p[0] for p in parts)
    total = sum(p[1] for p in parts)
    return overview_item_from_totals(
        sport="wnba", label="WNBA", correct=correct, total=total
    )


def season_overview_diagnostics(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, Any]:
    """Structured counts for admin/debug — same row sets as ``season_overview``."""
    r = _wnba_season_overview_row_sets(db, start=start, end=end)
    specs = [
        (
            "game_totals_ou",
            "Game totals O/U",
            "totals",
            "market_total",
            "recommendation",
            "actual_total",
        ),
        (
            "points_ou",
            "Points O/U",
            "points",
            "market_line",
            "recommendation",
            "actual_points",
        ),
        (
            "assists_ou",
            "Assists O/U",
            "assists",
            "market_line",
            "recommendation",
            "actual_assists",
        ),
        (
            "rebounds_ou",
            "Rebounds O/U",
            "rebounds",
            "market_line",
            "recommendation",
            "actual_rebounds",
        ),
    ]
    parts_out: list[dict[str, Any]] = []
    correct = 0
    total = 0
    for key, label, rk, lf, pf, af in specs:
        rows = r[rk]
        bd = ou_call_graded_breakdown(
            rows, line_field=lf, pick_field=pf, actual_field=af
        )
        c, t = bd["graded_correct"], bd["graded_total"]
        correct += c
        total += t
        parts_out.append(
            {
                "key": key,
                "label": label,
                "kind": "ou",
                "breakdown": bd,
                "graded_correct": c,
                "graded_total": t,
            }
        )
    return {
        "sport": "wnba",
        "date_bounds": {"start": start.isoformat(), "end": end.isoformat()},
        "overview": overview_item_from_totals(
            sport="wnba", label="WNBA", correct=correct, total=total
        ),
        "parts": parts_out,
    }
