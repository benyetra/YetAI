"""Per-day MLB projection accuracy.

Used by GET /api/v1/predictions/mlb/accuracy to render the
AccuracySummary cards above the projection tables.

Three buckets:

- Pitcher Ks O/U: count of FanDuel-line calls correct vs. wrong, with
  pushes excluded from the denominator. Also reports a K MAE (mean
  absolute error vs. projected_strikeouts) across rows that have an
  actual.

- Projected hits: success rate for batters we projected as "should get
  hits" (projected_hits >= 1). A batter is a success if actual_hits >= 1.

- Projected home runs: same shape but for home runs.

The compute_* functions take row-dicts (already shaped like the
predictions endpoint) so they're pure and trivially testable. The
public daily_accuracy() function wires the DB queries.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.predictions_models import (
    ProjectedHits,
    ProjectedHomers,
    StrikeoutActuals,
    StrikeoutProjections,
)


# ---------------------------------------------------------------------------
# Pure compute functions
# ---------------------------------------------------------------------------


def compute_pitcher_ko_ou(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Pitcher strikeouts vs FanDuel line accuracy.

    A row is countable only if it has all of: fanduel_line,
    fanduel_over_under, actual_strikeouts. actual == line is a push and
    drops out of total/correct but is reported separately.
    """
    total = 0
    correct = 0
    push = 0
    abs_errors: list[float] = []

    for row in rows:
        line = row.get("fanduel_line")
        pick = (row.get("fanduel_over_under") or "").strip().lower()
        actual = row.get("actual_strikeouts")
        projected = row.get("projected_strikeouts")

        if actual is not None and projected is not None:
            abs_errors.append(abs(float(projected) - float(actual)))

        if line is None or not pick or actual is None:
            continue

        if float(actual) == float(line):
            push += 1
            continue

        won_over = pick == "over" and float(actual) > float(line)
        won_under = pick == "under" and float(actual) < float(line)
        total += 1
        if won_over or won_under:
            correct += 1

    accuracy = correct / total if total else None
    mae = sum(abs_errors) / len(abs_errors) if abs_errors else None
    return {
        "total": total,
        "correct": correct,
        "push": push,
        "accuracy": accuracy,
        "mae": mae,
    }


def compute_hits(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Projected-hits success rate.

    Only batters where projected_hits >= 1 count. Success = actual_hits >= 1
    (any hits at all). Rows where actual_hits is None (actuals not yet
    written) are skipped from both numerator and denominator.
    """
    projected_batters = 0
    hits_made = 0
    for row in rows:
        projected = row.get("projected_hits")
        actual = row.get("actual_hits")
        if not projected or projected < 1:
            continue
        if actual is None:
            continue
        projected_batters += 1
        if actual >= 1:
            hits_made += 1
    rate = hits_made / projected_batters if projected_batters else None
    return {
        "projected_batters": projected_batters,
        "hits_made": hits_made,
        "success_rate": rate,
    }


def compute_homers(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Projected-homers success rate; same shape as compute_hits."""
    projected_batters = 0
    hr_hit = 0
    for row in rows:
        projected = row.get("projected_homers")
        actual = row.get("actual_homers")
        if not projected or projected < 1:
            continue
        if actual is None:
            continue
        projected_batters += 1
        if actual >= 1:
            hr_hit += 1
    rate = hr_hit / projected_batters if projected_batters else None
    return {
        "projected_batters": projected_batters,
        "hr_hit": hr_hit,
        "success_rate": rate,
    }


# ---------------------------------------------------------------------------
# DB-backed wrapper
# ---------------------------------------------------------------------------


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Fetch the day's projections, merge actuals, and compute the summary."""
    # Strikeouts: enrich each projection row with actuals via a dict lookup
    # rather than a JOIN — keeps the call cheap and avoids changing the
    # ORM query shape elsewhere.
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
                "pitcher_id": p.pitcher_id,
                "projected_strikeouts": p.projected_strikeouts,
                "fanduel_line": p.fanduel_line,
                "fanduel_over_under": p.fanduel_over_under,
                "actual_strikeouts": a.actual_strikeouts if a else None,
                "actual_innings_pitched": a.actual_innings_pitched if a else None,
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

    return {
        "date": target_date.isoformat(),
        "pitcher_ks_ou": compute_pitcher_ko_ou(k_rows),
        "projected_hits": compute_hits(hits_rows),
        "projected_homers": compute_homers(homer_rows),
        "available": bool(k_rows or hits_rows or homer_rows),
    }


def strikeout_actuals_by_pitcher(
    db: Session, *, target_date: date_type
) -> dict[str, StrikeoutActuals]:
    """Helper for the predictions endpoint: lookup map of pitcher_id → row.

    Used to enrich strikeout_projections with actual_strikeouts /
    actual_innings_pitched fields for past-date views.
    """
    return {
        r.pitcher_id: r
        for r in db.query(StrikeoutActuals)
        .filter(StrikeoutActuals.date == target_date)
        .all()
    }
