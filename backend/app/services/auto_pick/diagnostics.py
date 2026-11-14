"""Read-only diagnostics for auto-pick runs and projection coverage."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.database_models import AutoPickRun, ScoringConfig
from app.models.predictions_models import (
    GameProjections,
    NBASpreadProjections,
    NBATotalsProjections,
    NHLGoaliePredictions,
    NHLTeamTotalsPredictions,
    NFLSpreadProjections,
    NFLTotalsProjections,
    PointsProjections,
    PRAProjections,
    QBPredictions,
    RecvYdsPredictions,
    StealsProjections,
    StrikeoutProjections,
    ThreePointProjections,
    WNBAPointsProjections,
    WNBASpreadProjections,
    WNBATotalsProjections,
)
from app.services.auto_pick.candidate import utc_to_eastern


def projection_counts_for_day(db: Session, day: date) -> dict[str, int]:
    """Row counts that feed auto-pick sources for one US Eastern slate day.

    Each count uses the same date filter as the source that reads the table.
    """

    def n(model, *conds) -> int:
        return db.query(model).filter(*conds).count()

    return {
        # NBA
        "nba_spread_projections": n(
            NBASpreadProjections, NBASpreadProjections.game_date == day
        ),
        "nba_totals_projections": n(
            NBATotalsProjections, NBATotalsProjections.game_date == day
        ),
        "nba_points_props_with_line": n(
            PointsProjections,
            PointsProjections.date == day,
            PointsProjections.fanduel_line.isnot(None),
        ),
        "nba_steals_props_with_line": n(
            StealsProjections,
            StealsProjections.date == day,
            StealsProjections.fanduel_line.isnot(None),
        ),
        "nba_threes_props_with_line": n(
            ThreePointProjections,
            ThreePointProjections.date == day,
            ThreePointProjections.fanduel_line.isnot(None),
        ),
        "nba_pra_props_with_line": n(
            PRAProjections,
            PRAProjections.date == day,
            PRAProjections.fanduel_line.isnot(None),
        ),
        # WNBA
        "wnba_totals_projections": n(
            WNBATotalsProjections, WNBATotalsProjections.game_date == day
        ),
        "wnba_spread_projections": n(
            WNBASpreadProjections, WNBASpreadProjections.game_date == day
        ),
        "wnba_points_props_with_line": n(
            WNBAPointsProjections,
            WNBAPointsProjections.date == day,
            WNBAPointsProjections.market_line.isnot(None),
        ),
        # NFL
        "nfl_qb_passing_with_line": n(
            QBPredictions,
            # QBPredictions.game_date is a naive ET kickoff (same filter as the source).
            QBPredictions.game_date >= datetime.combine(day, time.min),
            QBPredictions.game_date
            < datetime.combine(day + timedelta(days=1), time.min),
            QBPredictions.ou_line.isnot(None),
        ),
        "nfl_spread_projections": n(
            NFLSpreadProjections, NFLSpreadProjections.game_date == day
        ),
        "nfl_totals_projections": n(
            NFLTotalsProjections, NFLTotalsProjections.game_date == day
        ),
        "nfl_receiving_yards_with_line": n(
            RecvYdsPredictions,
            RecvYdsPredictions.game_date == day,
            RecvYdsPredictions.ou_line.isnot(None),
        ),
        # NHL
        "nhl_totals_projections": n(
            NHLTeamTotalsPredictions, NHLTeamTotalsPredictions.game_date == day
        ),
        "nhl_goalie_saves_with_line": n(
            NHLGoaliePredictions,
            NHLGoaliePredictions.game_date == day,
            NHLGoaliePredictions.saves_line.isnot(None),
            NHLGoaliePredictions.was_scratch.isnot(True),
        ),
        # MLB
        "mlb_strikeout_with_line": n(
            StrikeoutProjections,
            StrikeoutProjections.date == day,
            StrikeoutProjections.fanduel_line.isnot(None),
            StrikeoutProjections.fanduel_line > 0,
        ),
        "mlb_game_projections": n(GameProjections, GameProjections.date == day),
    }


def summarize_drop_reasons(dropped: dict | None) -> dict[str, int]:
    """Aggregate drop reasons from auto_pick_runs.dropped_reasons.

    Reads the current shape ``{"counts": {...}, "top_rejected": [...]}`` and the
    legacy ``{event_id: reason}`` shape.
    """
    if not dropped:
        return {}
    buckets: dict[str, int] = {}
    if isinstance(dropped.get("counts"), dict):
        for reason, n in dropped["counts"].items():
            key = (reason or "unknown").split(":")[0]
            buckets[key] = buckets.get(key, 0) + int(n)
        return buckets
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

    run_day = utc_to_eastern(run.run_at or datetime.utcnow()).date()
    cfg = db.query(ScoringConfig).order_by(ScoringConfig.id.asc()).first()

    return {
        "found": True,
        "run": serialize_run(run),
        "slate_date_et": run_day.isoformat(),
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
    summary = summarize_drop_reasons(run.dropped_reasons)
    if run.candidates_considered == 0:
        hints.append(
            "No candidates: check that the ETL produced projections with market "
            "lines for this ET slate day (see projection_counts)."
        )
    elif run.candidates_selected == 0:
        for reason, text in (
            ("below_floor", "below the min score floor"),
            ("below_threshold", "below score_threshold"),
            ("non_positive_edge", "had no positive edge for the picked side"),
            ("no_play", "had no model recommendation"),
            ("ungradeable", "have no results source (can_grade is False)"),
            ("started_or_starting", "belong to games already started or starting"),
            ("start_time_unknown", "have no start time and it is past 12:00 ET"),
            ("odds_out_of_bounds", "were outside the configured odds range"),
            ("event_already_used", "were in games already picked today"),
            ("same_event", "were in a game already picked this run"),
            ("market_concentration", "hit the 2-per-league+market daily limit"),
        ):
            if summary.get(reason):
                hints.append(f"{summary[reason]} candidate(s) {text}.")
    return hints
