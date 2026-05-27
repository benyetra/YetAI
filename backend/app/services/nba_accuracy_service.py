"""Per-day NBA projection accuracy → unified bucket shape.

Buckets:
- Points O/U (FanDuel-line call accuracy + MAE)
- 3P Made O/U (FanDuel-line call accuracy + MAE)
- Steals O/U (FanDuel-line call accuracy + MAE)
- Assists O/U (FanDuel-line call accuracy + MAE)
- Rebounds O/U (FanDuel-line call accuracy + MAE)
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    ActualThreePointMade,
    AssistsActuals,
    AssistsProjections,
    PointsActuals,
    PointsProjections,
    ReboundsActuals,
    ReboundsProjections,
    StealsActuals,
    StealsProjections,
    ThreePointProjections,
)
from app.services.accuracy_shared import (
    AccuracyBucket,
    assemble,
    ou_call_bucket,
    ou_call_graded_counts,
    overview_item_from_totals,
)


def _merge_actuals_range(
    projections,
    actuals,
    *,
    pid_attr: str,
    actual_attr: str,
    actual_key: str,
) -> list[dict[str, Any]]:
    """Pair projections with actuals on (player_id, calendar date)."""
    by_key = {(getattr(a, pid_attr), a.date): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in projections:
        key = (getattr(p, pid_attr), p.date)
        a = by_key.get(key)
        row: dict[str, Any] = {c.name: getattr(p, c.name) for c in p.__table__.columns}
        row[actual_key] = getattr(a, actual_attr) if a else None
        out.append(row)
    return out


def _merge_actuals(
    projections, actuals, *, pid_attr: str, actual_attr: str
) -> list[dict[str, Any]]:
    """Pair projection rows with their per-player actual via an in-memory map.

    Returns row dicts with all projection columns plus the actual_* value
    (None if no actual was recorded yet).
    """
    by_pid = {getattr(a, pid_attr): a for a in actuals}
    out = []
    for p in projections:
        a = by_pid.get(getattr(p, pid_attr))
        # Pull every projection column onto the row dict — generic helpers
        # only read whatever field names the caller passes in.
        row: dict[str, Any] = {c.name: getattr(p, c.name) for c in p.__table__.columns}
        row["__actual"] = getattr(a, actual_attr) if a else None
        out.append(row)
    return out


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the NBA accuracy summary for `target_date`."""

    # --- Points ----------------------------------------------------------
    pts_proj = (
        db.query(PointsProjections).filter(PointsProjections.date == target_date).all()
    )
    pts_actuals = (
        db.query(PointsActuals).filter(PointsActuals.date == target_date).all()
    )
    pts_rows = _merge_actuals(
        pts_proj, pts_actuals, pid_attr="player_id", actual_attr="actual_points"
    )
    for row in pts_rows:
        row["actual_points"] = row.pop("__actual")

    # --- 3P --------------------------------------------------------------
    tpm_proj = (
        db.query(ThreePointProjections)
        .filter(ThreePointProjections.date == target_date)
        .all()
    )
    tpm_actuals = (
        db.query(ActualThreePointMade)
        .filter(ActualThreePointMade.date == target_date)
        .all()
    )
    tpm_rows = _merge_actuals(
        tpm_proj, tpm_actuals, pid_attr="player_id", actual_attr="actual_three_pt_made"
    )
    for row in tpm_rows:
        row["actual_three_pt_made"] = row.pop("__actual")

    # --- Steals ----------------------------------------------------------
    stl_proj = (
        db.query(StealsProjections).filter(StealsProjections.date == target_date).all()
    )
    stl_actuals = (
        db.query(StealsActuals).filter(StealsActuals.date == target_date).all()
    )
    stl_rows = _merge_actuals(
        stl_proj, stl_actuals, pid_attr="player_id", actual_attr="actual_steals"
    )
    for row in stl_rows:
        row["actual_steals"] = row.pop("__actual")

    # --- Assists ---------------------------------------------------------
    ast_proj = (
        db.query(AssistsProjections)
        .filter(AssistsProjections.date == target_date)
        .all()
    )
    ast_actuals = (
        db.query(AssistsActuals).filter(AssistsActuals.date == target_date).all()
    )
    ast_rows = _merge_actuals(
        ast_proj, ast_actuals, pid_attr="player_id", actual_attr="actual_assists"
    )
    for row in ast_rows:
        row["actual_assists"] = row.pop("__actual")

    # --- Rebounds --------------------------------------------------------
    reb_proj = (
        db.query(ReboundsProjections)
        .filter(ReboundsProjections.date == target_date)
        .all()
    )
    reb_actuals = (
        db.query(ReboundsActuals).filter(ReboundsActuals.date == target_date).all()
    )
    reb_rows = _merge_actuals(
        reb_proj, reb_actuals, pid_attr="player_id", actual_attr="actual_rebounds"
    )
    for row in reb_rows:
        row["actual_rebounds"] = row.pop("__actual")

    buckets: list[AccuracyBucket] = [
        ou_call_bucket(
            pts_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_points",
            projected_field="projected_points",
            label="Points O/U",
            key="points_ou",
        ),
        ou_call_bucket(
            tpm_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_three_pt_made",
            projected_field="projected_three_pt_made",
            label="3P Made O/U",
            key="three_pt_ou",
        ),
        ou_call_bucket(
            stl_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_steals",
            projected_field="projected_steals",
            label="Steals O/U",
            key="steals_ou",
        ),
        ou_call_bucket(
            ast_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_assists",
            projected_field="projected_assists",
            label="Assists O/U",
            key="assists_ou",
        ),
        ou_call_bucket(
            reb_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_rebounds",
            projected_field="projected_rebounds",
            label="Rebounds O/U",
            key="rebounds_ou",
        ),
    ]

    available = any([pts_rows, tpm_rows, stl_rows, ast_rows, reb_rows])
    return assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=available,
    )


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Window NBA accuracy — combined O/U hit rate across core props."""

    def _rng(proj_cls, act_cls, *, pid_attr: str, actual_attr: str, actual_key: str):
        proj = (
            db.query(proj_cls)
            .filter(proj_cls.date >= start, proj_cls.date <= end)
            .all()
        )
        act = db.query(act_cls).filter(act_cls.date >= start, act_cls.date <= end).all()
        return _merge_actuals_range(
            proj, act, pid_attr=pid_attr, actual_attr=actual_attr, actual_key=actual_key
        )

    pts_rows = _rng(
        PointsProjections,
        PointsActuals,
        pid_attr="player_id",
        actual_attr="actual_points",
        actual_key="actual_points",
    )
    tpm_rows = _rng(
        ThreePointProjections,
        ActualThreePointMade,
        pid_attr="player_id",
        actual_attr="actual_three_pt_made",
        actual_key="actual_three_pt_made",
    )
    stl_rows = _rng(
        StealsProjections,
        StealsActuals,
        pid_attr="player_id",
        actual_attr="actual_steals",
        actual_key="actual_steals",
    )
    ast_rows = _rng(
        AssistsProjections,
        AssistsActuals,
        pid_attr="player_id",
        actual_attr="actual_assists",
        actual_key="actual_assists",
    )
    reb_rows = _rng(
        ReboundsProjections,
        ReboundsActuals,
        pid_attr="player_id",
        actual_attr="actual_rebounds",
        actual_key="actual_rebounds",
    )

    parts = [
        ou_call_graded_counts(
            pts_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_points",
        ),
        ou_call_graded_counts(
            tpm_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_three_pt_made",
        ),
        ou_call_graded_counts(
            stl_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_steals",
        ),
        ou_call_graded_counts(
            ast_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_assists",
        ),
        ou_call_graded_counts(
            reb_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_rebounds",
        ),
    ]
    correct = sum(p[0] for p in parts)
    total = sum(p[1] for p in parts)
    return overview_item_from_totals(
        sport="nba", label="NBA", correct=correct, total=total
    )
