"""Read-only diagnostics for auto-pick runs and projection coverage."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.database_models import AutoPickRun, ScoringConfig
from app.models.predictions_models import (
    Hitter,
    NBASpreadProjections,
    NBATotalsProjections,
    PointsProjections,
    StealsProjections,
    StrikeoutProjections,
    WNBAPointsProjections,
    WNBASpreadProjections,
    WNBATotalsProjections,
)


def projection_counts_for_day(db: Session, day: date) -> dict[str, int]:
    """Row counts that feed auto-pick sources for a single calendar day (UTC)."""
    return {
        "nba_spread_projections": db.query(NBASpreadProjections)
        .filter(NBASpreadProjections.game_date == day)
        .count(),
        "nba_totals_projections": db.query(NBATotalsProjections)
        .filter(NBATotalsProjections.game_date == day)
        .count(),
        "nba_points_props_with_line": db.query(PointsProjections)
        .filter(
            PointsProjections.date == day,
            PointsProjections.fanduel_line.isnot(None),
        )
        .count(),
        "nba_steals_props_with_line": db.query(StealsProjections)
        .filter(
            StealsProjections.date == day,
            StealsProjections.fanduel_line.isnot(None),
        )
        .count(),
        "mlb_strikeout_with_line": db.query(StrikeoutProjections)
        .filter(
            StrikeoutProjections.date == day,
            StrikeoutProjections.fanduel_line.isnot(None),
            StrikeoutProjections.fanduel_line > 0,
        )
        .count(),
        "mlb_hits_today": db.query(Hitter)
        .filter(
            Hitter.game_time >= datetime.combine(day, datetime.min.time()),
            Hitter.game_time <= datetime.combine(day, datetime.max.time()),
        )
        .count(),
        "wnba_totals_projections": db.query(WNBATotalsProjections)
        .filter(WNBATotalsProjections.game_date == day)
        .count(),
        "wnba_spread_projections": db.query(WNBASpreadProjections)
        .filter(WNBASpreadProjections.game_date == day)
        .count(),
        "wnba_points_props_with_line": db.query(WNBAPointsProjections)
        .filter(
            WNBAPointsProjections.date == day,
            WNBAPointsProjections.market_line.isnot(None),
        )
        .count(),
    }


def summarize_drop_reasons(dropped: dict[str, str] | None) -> dict[str, int]:
    """Aggregate drop_reason strings from auto_pick_runs.dropped_reasons JSONB."""
    if not dropped:
        return {}
    buckets: dict[str, int] = {}
    for reason in dropped.values():
        key = (reason or "unknown").split(":")[0]
        buckets[key] = buckets.get(key, 0) + 1
    return buckets


def serialize_run(run: AutoPickRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "run_at": run.run_at.isoformat() if run.run_at else None,
        "status": run.status.value if run.status else None,
        "candidates_considered": run.candidates_considered,
        "candidates_selected": run.candidates_selected,
        "dropped_reasons": run.dropped_reasons,
        "drop_reason_summary": summarize_drop_reasons(run.dropped_reasons),
        "error": run.error,
    }


def get_run_diagnostics(db: Session, run_id: int) -> dict[str, Any]:
    run = db.query(AutoPickRun).filter(AutoPickRun.id == run_id).first()
    if not run:
        return {"found": False, "run_id": run_id}

    run_day = run.run_at.date() if run.run_at else datetime.utcnow().date()
    cfg = db.query(ScoringConfig).order_by(ScoringConfig.id.asc()).first()

    return {
        "found": True,
        "run": serialize_run(run),
        "run_day_utc": run_day.isoformat(),
        "projection_counts": projection_counts_for_day(db, run_day),
        "scoring_config": (
            {
                "score_threshold": cfg.score_threshold,
                "odds_min": cfg.odds_min,
                "odds_max": cfg.odds_max,
                "max_picks_per_day": cfg.max_picks_per_day,
            }
            if cfg
            else None
        ),
        "hints": _hints_for_run(run),
    }


def _hints_for_run(run: AutoPickRun) -> list[str]:
    hints: list[str] = []
    if run.candidates_considered == 0:
        hints.append(
            "No candidates: run MLB/NBA ETL for this UTC day, or check date-window "
            "(fixed in orchestrator to use start/end of UTC day)."
        )
    elif run.candidates_selected == 0:
        summary = summarize_drop_reasons(run.dropped_reasons)
        if summary.get("below_threshold"):
            hints.append(
                f"{summary['below_threshold']} candidate(s) below score_threshold — "
                "inspect dropped_reasons or lower scoring_config.score_threshold."
            )
        if summary.get("odds_out_of_bounds"):
            hints.append(
                "Some candidates rejected for odds outside configured min/max."
            )
        if summary.get("correlation_same_event"):
            hints.append("Some candidates dropped as duplicate event_id.")
    return hints
