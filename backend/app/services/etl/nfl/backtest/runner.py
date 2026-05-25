"""Replay NFL predictions joined to actuals (DB) or synthetic rows (offline tests)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.services.etl.nfl.backtest.scorer import NFLBacktestScorer
from app.services.etl.nfl.qb_passing_yards_ml import (
    shadow_ml_yards_from_feature_importance,
)

logger = logging.getLogger(__name__)

DEFAULT_QUICK_WEEKS = 10


@dataclass
class NFLBacktestReplayResult:
    scorer: NFLBacktestScorer
    weeks_used: list[tuple[int, int]] = field(default_factory=list)
    rows_scored: dict[str, int] = field(default_factory=dict)


def _limit_weeks(
    weeks: list[tuple[int, int]],
    *,
    quick: bool,
    max_weeks: int | None,
) -> list[tuple[int, int]]:
    if not weeks:
        return []
    ordered = sorted(set(weeks), reverse=True)
    if quick:
        limit = max_weeks if max_weeks is not None else DEFAULT_QUICK_WEEKS
        return ordered[:limit]
    return ordered


def _fetch_distinct_weeks(
    session: Session,
    season: int,
    start_week: int,
    end_week: int,
) -> list[tuple[int, int]]:
    from app.models.predictions_models import QBActuals, QBPredictions

    weeks: set[tuple[int, int]] = set()
    for model in (QBPredictions, QBActuals):
        rows = (
            session.query(model.season, model.week)
            .filter(
                model.season == season,
                model.week >= start_week,
                model.week <= end_week,
            )
            .distinct()
            .all()
        )
        weeks.update((int(r[0]), int(r[1])) for r in rows)
    return sorted(weeks)


def _load_qb_pairs(
    session: Session,
    season: int,
    weeks: Sequence[tuple[int, int]],
) -> list[tuple[Any, Any]]:
    from app.models.predictions_models import QBActuals, QBPredictions

    if not weeks:
        return []
    week_nums = {w for _, w in weeks}
    preds = (
        session.query(QBPredictions)
        .filter(QBPredictions.season == season, QBPredictions.week.in_(week_nums))
        .all()
    )
    actuals = (
        session.query(QBActuals)
        .filter(QBActuals.season == season, QBActuals.week.in_(week_nums))
        .all()
    )
    actual_index = {(a.qb_player_id, a.season, a.week): a for a in actuals}
    pairs: list[tuple[Any, Any]] = []
    for pred in preds:
        key = (pred.qb_player_id, pred.season, pred.week)
        actual = actual_index.get(key)
        if actual is not None:
            pairs.append((pred, actual))
    return pairs


def _load_kicker_pairs(
    session: Session,
    season: int,
    weeks: Sequence[tuple[int, int]],
) -> list[tuple[Any, Any]]:
    from app.models.predictions_models import KickerActuals, KickerPredictions

    _ = season, weeks  # kicker tables keyed by game date, not week column
    preds = session.query(KickerPredictions).all()
    actuals = session.query(KickerActuals).all()
    if not preds or not actuals:
        return []

    pred_by_kicker_date: dict[tuple[str, Any], Any] = {}
    for pred in preds:
        if not pred.game_date:
            continue
        pred_by_kicker_date[(pred.kicker_player_id, pred.game_date.date())] = pred

    pairs: list[tuple[Any, Any]] = []
    for actual in actuals:
        pred = pred_by_kicker_date.get((actual.kicker_id, actual.date))
        if pred is not None:
            pairs.append((pred, actual))
    return pairs


def score_synthetic_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    scorer: NFLBacktestScorer | None = None,
) -> NFLBacktestScorer:
    result_scorer = scorer or NFLBacktestScorer()
    for row in rows:
        market = row.get("market")
        predicted = float(row["predicted"])
        actual = float(row["actual"])
        line = row.get("line")
        if market == "qb":
            result_scorer.add_qb_result(
                predicted,
                actual,
                ou_line=float(line) if line is not None else None,
                season=row.get("season"),
                week=row.get("week"),
                prediction_method=row.get("prediction_method"),
            )
        elif market == "kicker":
            result_scorer.add_kicker_result(
                predicted,
                actual,
                season=row.get("season"),
                week=row.get("week"),
            )
        else:
            raise ValueError(f"Unknown market: {market!r}")
    return result_scorer


def _score_db_pairs(
    qb_pairs: Sequence[tuple[Any, Any]],
    kicker_pairs: Sequence[tuple[Any, Any]],
    *,
    scorer: NFLBacktestScorer | None = None,
) -> NFLBacktestScorer:
    result_scorer = scorer or NFLBacktestScorer()

    for pred, actual in qb_pairs:
        ml_yards = shadow_ml_yards_from_feature_importance(pred.feature_importance)
        result_scorer.add_qb_result(
            pred.predicted_passing_yards,
            actual.actual_passing_yards,
            ou_line=float(pred.ou_line) if pred.ou_line is not None else None,
            season=pred.season,
            week=pred.week,
            qb_player_id=pred.qb_player_id,
            prediction_method=pred.prediction_method,
            ml_predicted_yards=ml_yards,
        )

    for pred, actual in kicker_pairs:
        projected = getattr(pred, "predicted_fg_made", None)
        if projected is None:
            projected = getattr(pred, "projected_field_goals", None)
        if projected is None:
            continue
        result_scorer.add_kicker_result(
            float(projected),
            actual.actual_field_goals_made,
            kicker_player_id=pred.kicker_player_id,
        )

    return result_scorer


def run_backtest_replay(
    *,
    session: Session | None = None,
    season: int | None = None,
    start_week: int = 1,
    end_week: int = 18,
    quick: bool = False,
    max_weeks: int | None = None,
    synthetic_rows: Sequence[Mapping[str, Any]] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> NFLBacktestReplayResult:
    from app.services.etl.nfl.nfl_common import get_nfl_season

    scorer = NFLBacktestScorer()
    weeks_used: list[tuple[int, int]] = []
    counts = {"qb": 0, "kicker": 0}

    if synthetic_rows:
        score_synthetic_rows(synthetic_rows, scorer=scorer)
        for row in synthetic_rows:
            market = row.get("market")
            if market in counts:
                counts[market] += 1

    if session is not None or session_factory is not None:
        own_session = session is None
        db = session if session is not None else session_factory()  # type: ignore[misc]
        try:
            resolved_season = season if season is not None else get_nfl_season()
            all_weeks = _fetch_distinct_weeks(db, resolved_season, start_week, end_week)
            weeks_used = _limit_weeks(all_weeks, quick=quick, max_weeks=max_weeks)
            if not weeks_used and not synthetic_rows:
                logger.warning(
                    "No weeks in range season=%s weeks %s..%s",
                    resolved_season,
                    start_week,
                    end_week,
                )
            qb_pairs = _load_qb_pairs(db, resolved_season, weeks_used)
            kicker_pairs = _load_kicker_pairs(db, resolved_season, weeks_used)
            _score_db_pairs(qb_pairs, kicker_pairs, scorer=scorer)
            counts["qb"] += len(qb_pairs)
            counts["kicker"] += len(kicker_pairs)
        finally:
            if own_session:
                db.close()

    return NFLBacktestReplayResult(
        scorer=scorer,
        weeks_used=weeks_used,
        rows_scored=counts,
    )
