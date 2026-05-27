"""Per-day MLB projection accuracy → unified bucket shape.

Buckets:
- Pitcher Ks O/U, Projected Hits, Projected Home Runs (prop boards)
- Game Moneyline, Spread, Total (edge plays from game projections)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type
from typing import Any

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    GameActuals,
    GameProjections,
    ProjectedHits,
    ProjectedHomers,
    StrikeoutActuals,
    StrikeoutProjections,
)
from app.services.accuracy_shared import (
    assemble,
    edge_play_bucket,
    edge_play_graded_counts,
    hit_rate_bucket,
    hit_rate_graded_counts,
    ou_call_bucket,
    ou_call_graded_counts,
    overview_item_from_totals,
)
from app.services.mlb_game_picks import enrich_game_projection_row


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


def _merge_game_rows_range(
    db: Session, *, start: date_type, end: date_type
) -> list[dict[str, Any]]:
    """Join game projections with final scores across a date range."""
    projections = (
        db.query(GameProjections)
        .filter(GameProjections.date >= start, GameProjections.date <= end)
        .all()
    )
    actuals_by_gid = {
        a.game_id: a
        for a in db.query(GameActuals)
        .filter(GameActuals.date >= start, GameActuals.date <= end)
        .all()
    }
    rows: list[dict[str, Any]] = []
    for proj in projections:
        row = {c.name: getattr(proj, c.name) for c in proj.__table__.columns}
        actual = actuals_by_gid.get(proj.game_id)
        if actual:
            row.update(
                {
                    "actual_home_score": actual.home_score,
                    "actual_away_score": actual.away_score,
                    "actual_total_runs": actual.total_runs,
                    "actual_winner": actual.winner,
                    "ml_correct": actual.ml_correct,
                    "spread_correct": actual.spread_correct,
                    "total_correct": actual.total_correct,
                }
            )
        rows.append(enrich_game_projection_row(row))
    return rows


def _merge_game_rows(db: Session, *, target_date: date_type) -> list[dict[str, Any]]:
    """Join game projections with final scores for grading buckets."""
    projections = (
        db.query(GameProjections).filter(GameProjections.date == target_date).all()
    )
    actuals_by_gid = {
        a.game_id: a
        for a in db.query(GameActuals).filter(GameActuals.date == target_date).all()
    }
    rows: list[dict[str, Any]] = []
    for proj in projections:
        row = {c.name: getattr(proj, c.name) for c in proj.__table__.columns}
        actual = actuals_by_gid.get(proj.game_id)
        if actual:
            row.update(
                {
                    "actual_home_score": actual.home_score,
                    "actual_away_score": actual.away_score,
                    "actual_total_runs": actual.total_runs,
                    "actual_winner": actual.winner,
                    "ml_correct": actual.ml_correct,
                    "spread_correct": actual.spread_correct,
                    "total_correct": actual.total_correct,
                }
            )
        rows.append(enrich_game_projection_row(row))
    return rows


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Fetch the day's MLB projections + actuals, return the bucketed summary."""
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

    game_rows = _merge_game_rows(db, target_date=target_date)

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
        edge_play_bucket(
            game_rows,
            pick_field="ml_recommendation",
            correct_field="ml_correct",
            label="Game Moneyline",
            key="game_moneyline",
            secondary="ML edge plays (HOME/AWAY)",
        ),
        edge_play_bucket(
            game_rows,
            pick_field="spread_recommendation",
            correct_field="spread_correct",
            label="Game Spread",
            key="game_spread",
            secondary="Spread edge plays vs market line",
        ),
        ou_call_bucket(
            game_rows,
            line_field="market_total",
            pick_field="total_recommendation",
            actual_field="actual_total_runs",
            projected_field="projected_total",
            label="Game Total",
            key="game_total",
        ),
    ]

    out = assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=bool(k_rows or hits_rows or homer_rows or game_rows),
    )
    by_version = _strikeout_accuracy_by_model_version(k_rows)
    if by_version:
        out["strikeout_by_model_version"] = by_version
    return out


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Season (or arbitrary window) MLB accuracy — one combined hit rate."""
    proj_rows = (
        db.query(StrikeoutProjections)
        .filter(
            StrikeoutProjections.date >= start,
            StrikeoutProjections.date <= end,
        )
        .all()
    )
    actuals_by_pid = {
        r.pitcher_id: r
        for r in db.query(StrikeoutActuals)
        .filter(
            StrikeoutActuals.date >= start,
            StrikeoutActuals.date <= end,
        )
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
            }
        )

    hits_rows = [
        {"projected_hits": r.projected_hits, "actual_hits": r.actual_hits}
        for r in db.query(ProjectedHits)
        .filter(ProjectedHits.date >= start, ProjectedHits.date <= end)
        .all()
    ]
    homer_rows = [
        {"projected_homers": r.projected_homers, "actual_homers": r.actual_homers}
        for r in db.query(ProjectedHomers)
        .filter(ProjectedHomers.date >= start, ProjectedHomers.date <= end)
        .all()
    ]

    game_rows = _merge_game_rows_range(db, start=start, end=end)

    parts = [
        ou_call_graded_counts(
            k_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_strikeouts",
        ),
        hit_rate_graded_counts(
            hits_rows,
            actual_field="actual_hits",
            projected_field="projected_hits",
            threshold=1,
        ),
        hit_rate_graded_counts(
            homer_rows,
            actual_field="actual_homers",
            projected_field="projected_homers",
            threshold=1,
        ),
        edge_play_graded_counts(
            game_rows, pick_field="ml_recommendation", correct_field="ml_correct"
        ),
        edge_play_graded_counts(
            game_rows,
            pick_field="spread_recommendation",
            correct_field="spread_correct",
        ),
        ou_call_graded_counts(
            game_rows,
            line_field="market_total",
            pick_field="total_recommendation",
            actual_field="actual_total_runs",
        ),
    ]
    correct = sum(p[0] for p in parts)
    total = sum(p[1] for p in parts)
    return overview_item_from_totals(
        sport="mlb", label="MLB", correct=correct, total=total
    )
