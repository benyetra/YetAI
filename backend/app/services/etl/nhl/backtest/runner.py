"""Replay NHL predictions joined to actuals (DB) or synthetic rows (offline tests)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.services.etl.nhl.backtest.scorer import NHLBacktestScorer
from app.services.etl.nhl.goalie_saves_ml import shadow_ml_saves_from_features_used
from app.services.etl.nhl.player_shots_ml import shadow_ml_sog_from_features_used
from app.services.etl.nhl.team_totals_ml import shadow_ml_total_from_features_used

logger = logging.getLogger(__name__)

DEFAULT_QUICK_SLATES = 10


@dataclass
class NHLBacktestReplayResult:
    """Outcome of a replay run."""

    scorer: NHLBacktestScorer
    slates_used: list[date] = field(default_factory=list)
    rows_scored: dict[str, int] = field(default_factory=dict)


def _limit_slate_dates(
    dates: list[date],
    *,
    quick: bool,
    max_slates: int | None,
) -> list[date]:
    if not dates:
        return []
    ordered = sorted(set(dates), reverse=True)
    if quick:
        limit = max_slates if max_slates is not None else DEFAULT_QUICK_SLATES
        return ordered[:limit]
    return ordered


def _fetch_distinct_slate_dates(
    session: Session,
    start: date,
    end: date,
) -> list[date]:
    from app.models.predictions_models import (
        NHLGoaliePredictions,
        NHLPlayerShotsPredictions,
        NHLTeamTotalsPredictions,
    )

    dates: set[date] = set()
    for model in (
        NHLGoaliePredictions,
        NHLPlayerShotsPredictions,
        NHLTeamTotalsPredictions,
    ):
        rows = (
            session.query(model.game_date)
            .filter(model.game_date >= start, model.game_date <= end)
            .distinct()
            .all()
        )
        dates.update(r[0] for r in rows)
    return sorted(dates)


def _load_goalie_pairs(
    session: Session,
    slate_dates: Sequence[date],
) -> list[tuple[Any, Any]]:
    from app.models.predictions_models import NHLGoalieActuals, NHLGoaliePredictions

    if not slate_dates:
        return []
    preds = (
        session.query(NHLGoaliePredictions)
        .filter(NHLGoaliePredictions.game_date.in_(slate_dates))
        .all()
    )
    actuals = (
        session.query(NHLGoalieActuals)
        .filter(NHLGoalieActuals.game_date.in_(slate_dates))
        .all()
    )
    actual_index: dict[tuple[int | None, int, date], Any] = {}
    for row in actuals:
        key = (row.game_id, row.goalie_id, row.game_date)
        actual_index[key] = row

    pairs: list[tuple[Any, Any]] = []
    for pred in preds:
        key = (pred.game_id, pred.goalie_id, pred.game_date)
        actual = actual_index.get(key)
        if actual is None and pred.game_id is None:
            for (gid, gid_goalie, gd), act in actual_index.items():
                if gid_goalie == pred.goalie_id and gd == pred.game_date:
                    actual = act
                    break
        if actual is not None:
            pairs.append((pred, actual))
    return pairs


def _load_sog_pairs(
    session: Session, slate_dates: Sequence[date]
) -> list[tuple[Any, Any]]:
    from app.models.predictions_models import (
        NHLPlayerShotsActuals,
        NHLPlayerShotsPredictions,
    )

    if not slate_dates:
        return []
    preds = (
        session.query(NHLPlayerShotsPredictions)
        .filter(NHLPlayerShotsPredictions.game_date.in_(slate_dates))
        .all()
    )
    actuals = (
        session.query(NHLPlayerShotsActuals)
        .filter(NHLPlayerShotsActuals.game_date.in_(slate_dates))
        .all()
    )
    actual_index = {(row.player_id, row.game_date): row for row in actuals}
    pairs: list[tuple[Any, Any]] = []
    for pred in preds:
        actual = actual_index.get((pred.player_id, pred.game_date))
        if actual is not None:
            pairs.append((pred, actual))
    return pairs


def _load_totals_pairs(
    session: Session,
    slate_dates: Sequence[date],
) -> list[tuple[Any, Any]]:
    from app.models.predictions_models import (
        NHLTeamTotalsActuals,
        NHLTeamTotalsPredictions,
    )

    if not slate_dates:
        return []
    preds = (
        session.query(NHLTeamTotalsPredictions)
        .filter(NHLTeamTotalsPredictions.game_date.in_(slate_dates))
        .all()
    )
    actuals = (
        session.query(NHLTeamTotalsActuals)
        .filter(NHLTeamTotalsActuals.game_date.in_(slate_dates))
        .all()
    )
    actual_index = {
        (row.home_team_id, row.away_team_id, row.game_date): row for row in actuals
    }
    pairs: list[tuple[Any, Any]] = []
    for pred in preds:
        key = (pred.home_team_id, pred.away_team_id, pred.game_date)
        actual = actual_index.get(key)
        if actual is not None:
            pairs.append((pred, actual))
    return pairs


def score_synthetic_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    scorer: NHLBacktestScorer | None = None,
) -> NHLBacktestScorer:
    """Score in-memory prediction/actual pairs (no DB).

    Each row must include ``market`` in ``goalie``, ``sog``, or ``totals`` plus
    ``predicted`` and ``actual``. Optional ``line`` for O/U grading.
    """
    result_scorer = scorer or NHLBacktestScorer()
    for row in rows:
        market = row["market"]
        predicted = float(row["predicted"])
        actual = row["actual"]
        line = row.get("line")
        game_date = row.get("game_date")
        if market == "goalie":
            ml_pred = row.get("ml_predicted")
            if ml_pred is None and isinstance(row.get("features_used"), dict):
                ml_pred = shadow_ml_saves_from_features_used(row["features_used"])
            result_scorer.add_goalie_result(
                predicted,
                actual,
                saves_line=line,
                game_date=str(game_date) if game_date else None,
                goalie_id=row.get("goalie_id"),
                ml_predicted_saves=float(ml_pred) if ml_pred is not None else None,
            )
        elif market == "sog":
            ml_pred = row.get("ml_predicted")
            if ml_pred is None and isinstance(row.get("features_used"), dict):
                ml_pred = shadow_ml_sog_from_features_used(row["features_used"])
            result_scorer.add_sog_result(
                predicted,
                actual,
                shots_line=line,
                game_date=str(game_date) if game_date else None,
                player_id=row.get("player_id"),
                ml_predicted_shots=float(ml_pred) if ml_pred is not None else None,
            )
        elif market == "totals":
            ml_pred = row.get("ml_predicted")
            if ml_pred is None and isinstance(row.get("features_used"), dict):
                ml_pred = shadow_ml_total_from_features_used(row["features_used"])
            result_scorer.add_totals_result(
                predicted,
                actual,
                ou_line=line,
                game_date=str(game_date) if game_date else None,
                game_id=row.get("game_id"),
                ml_predicted_total=float(ml_pred) if ml_pred is not None else None,
            )
        else:
            raise ValueError(f"Unknown market: {market!r}")
    return result_scorer


def _score_db_pairs(
    goalie_pairs: Sequence[tuple[Any, Any]],
    sog_pairs: Sequence[tuple[Any, Any]],
    totals_pairs: Sequence[tuple[Any, Any]],
    *,
    scorer: NHLBacktestScorer | None = None,
) -> NHLBacktestScorer:
    result_scorer = scorer or NHLBacktestScorer()

    for pred, actual in goalie_pairs:
        line = pred.saves_line or actual.saves_line
        ml_saves = shadow_ml_saves_from_features_used(pred.features_used)
        result_scorer.add_goalie_result(
            pred.predicted_saves,
            actual.actual_saves,
            saves_line=line,
            game_date=str(pred.game_date),
            goalie_id=pred.goalie_id,
            ml_predicted_saves=ml_saves,
        )

    for pred, actual in sog_pairs:
        line = pred.shots_line or actual.shots_line
        ml_shots = shadow_ml_sog_from_features_used(pred.features_used)
        result_scorer.add_sog_result(
            pred.predicted_shots,
            actual.actual_shots,
            shots_line=line,
            game_date=str(pred.game_date),
            player_id=pred.player_id,
            ml_predicted_shots=ml_shots,
        )

    for pred, actual in totals_pairs:
        line = (
            pred.draftkings_ou_line
            or pred.suggested_ou_line
            or actual.draftkings_ou_line
        )
        predicted_total = pred.predicted_total_goals
        ml_total = shadow_ml_total_from_features_used(pred.features_used)
        result_scorer.add_totals_result(
            predicted_total,
            actual.actual_total_goals,
            ou_line=float(line) if line is not None else None,
            game_date=str(pred.game_date),
            game_id=actual.game_id,
            ml_predicted_total=ml_total,
        )

    return result_scorer


def run_backtest_replay(
    *,
    session: Session | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    quick: bool = False,
    max_slates: int | None = None,
    synthetic_rows: Sequence[Mapping[str, Any]] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> NHLBacktestReplayResult:
    """Replay predictions vs actuals from DB and/or synthetic rows."""
    scorer = NHLBacktestScorer()
    slates: list[date] = []
    counts = {"goalie": 0, "sog": 0, "totals": 0}

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
            if start_date is None or end_date is None:
                raise ValueError("start_date and end_date required for DB replay")
            all_dates = _fetch_distinct_slate_dates(db, start_date, end_date)
            slates = _limit_slate_dates(all_dates, quick=quick, max_slates=max_slates)
            if not slates and not synthetic_rows:
                logger.warning("No slate dates in range %s..%s", start_date, end_date)
            goalie_pairs = _load_goalie_pairs(db, slates)
            sog_pairs = _load_sog_pairs(db, slates)
            totals_pairs = _load_totals_pairs(db, slates)
            _score_db_pairs(goalie_pairs, sog_pairs, totals_pairs, scorer=scorer)
            counts["goalie"] += len(goalie_pairs)
            counts["sog"] += len(sog_pairs)
            counts["totals"] += len(totals_pairs)
        finally:
            if own_session:
                db.close()

    return NHLBacktestReplayResult(
        scorer=scorer,
        slates_used=slates,
        rows_scored=counts,
    )
