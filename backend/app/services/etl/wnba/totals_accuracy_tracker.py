"""Compute WNBA totals projection accuracy over rolling windows.

Joins WNBATotalsProjections ↔ WNBATotalsActuals on (game_date, home_team_name,
away_team_name) and writes three rows per run to WNBATotalsAccuracy: last 7,
last 30, season-to-date.

Compares heuristic vs ML shadow (``factors.ml_shadow``) and recommends promoting
``WNBA_TOTALS_ML_ENABLED`` when ML wins on the season window.
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBATotalsAccuracy,
    WNBATotalsActuals,
    WNBATotalsProjections,
)
from app.services.etl.wnba._db_upsert import replace_matching
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba.totals_ml import shadow_from_factors

logger = logging.getLogger(__name__)

WNBA_SEASON_START_MONTH = 5  # WNBA season starts May 1
MIN_GAMES_FOR_PROMOTE = 20


def _season_start(today: date) -> date:
    return date(today.year, WNBA_SEASON_START_MONTH, 1)


def _mae(errors: list[float]) -> float | None:
    if not errors:
        return None
    return sum(errors) / len(errors)


def should_promote_totals_ml(
    *,
    heuristic_mae: float | None,
    ml_mae: float | None,
    ml_games: int,
    min_games: int = MIN_GAMES_FOR_PROMOTE,
) -> bool:
    """True when ML shadow beats heuristic MAE with enough paired games."""
    if heuristic_mae is None or ml_mae is None:
        return False
    if ml_games < min_games:
        return False
    return ml_mae < heuristic_mae


def _compute_window(db, start: date, end: date) -> dict:
    """Return MAE metrics + heuristic/ml shadow comparison for the window."""
    rows = (
        db.query(WNBATotalsProjections, WNBATotalsActuals)
        .join(
            WNBATotalsActuals,
            (WNBATotalsProjections.game_date == WNBATotalsActuals.game_date)
            & (WNBATotalsProjections.home_team_name == WNBATotalsActuals.home_team_name)
            & (
                WNBATotalsProjections.away_team_name == WNBATotalsActuals.away_team_name
            ),
        )
        .filter(WNBATotalsProjections.game_date >= start)
        .filter(WNBATotalsProjections.game_date <= end)
        .all()
    )
    if not rows:
        return {
            "mae": None,
            "rmse": None,
            "directional": None,
            "total": 0,
            "heuristic_mae": None,
            "ml_mae": None,
            "ml_games": 0,
            "recommend_promote": False,
        }

    errs: list[float] = []
    heuristic_errs: list[float] = []
    ml_errs: list[float] = []
    correct_direction = 0
    counted_direction = 0
    for proj, actual in rows:
        err = proj.projected_total - actual.actual_total
        errs.append(err)
        shadow = shadow_from_factors(getattr(proj, "factors", None))
        h_total = shadow.get("heuristic_total")
        if h_total is None:
            h_total = proj.projected_total
        if h_total is not None:
            heuristic_errs.append(abs(float(actual.actual_total) - float(h_total)))
        ml_total = shadow.get("ml_total")
        if ml_total is not None:
            ml_errs.append(abs(float(actual.actual_total) - float(ml_total)))

        if proj.market_total is not None:
            our_side_over = proj.projected_total > proj.market_total
            actual_over = actual.actual_total > proj.market_total
            if (
                proj.projected_total != proj.market_total
                and actual.actual_total != proj.market_total
            ):
                counted_direction += 1
                if our_side_over == actual_over:
                    correct_direction += 1

    mae = sum(abs(e) for e in errs) / len(errs)
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    directional = correct_direction / counted_direction if counted_direction else None
    heuristic_mae = _mae(heuristic_errs)
    ml_mae = _mae(ml_errs)
    ml_games = len(ml_errs)
    return {
        "mae": mae,
        "rmse": rmse,
        "directional": directional,
        "total": len(rows),
        "heuristic_mae": heuristic_mae,
        "ml_mae": ml_mae,
        "ml_games": ml_games,
        "recommend_promote": should_promote_totals_ml(
            heuristic_mae=heuristic_mae,
            ml_mae=ml_mae,
            ml_games=ml_games,
        ),
    }


def run() -> dict:
    today = now_eastern().date()
    windows = [
        ("last_7", today - timedelta(days=7), today),
        ("last_30", today - timedelta(days=30), today),
        ("season", _season_start(today), today),
    ]
    db = SessionLocal()
    accuracy_rows: list[dict] = []
    window_stats: dict[str, dict] = {}
    try:
        for label, start, end in windows:
            stats = _compute_window(db, start, end)
            window_stats[label] = stats
            if stats["total"] == 0:
                continue
            accuracy_rows.append(
                {
                    "date_range_start": start,
                    "date_range_end": end,
                    "total_games": stats["total"],
                    "mean_absolute_error": stats["mae"],
                    "root_mean_square_error": stats["rmse"],
                    "directional_accuracy": stats["directional"],
                    "heuristic_mean_absolute_error": stats["heuristic_mae"],
                    "ml_mean_absolute_error": stats["ml_mae"],
                    "created_at": datetime.utcnow(),
                }
            )
            logger.info(
                "WNBA totals accuracy %s: primary_mae=%s heuristic_mae=%s ml_mae=%s "
                "ml_games=%s recommend_promote=%s",
                label,
                stats["mae"],
                stats["heuristic_mae"],
                stats["ml_mae"],
                stats["ml_games"],
                stats["recommend_promote"],
            )
        replace_matching(
            db,
            WNBATotalsAccuracy,
            accuracy_rows,
            match_keys=["date_range_start", "date_range_end"],
        )
        db.commit()
        season = window_stats.get("season") or {}
        recommend = bool(season.get("recommend_promote"))
        if recommend:
            logger.warning(
                "WNBA totals ML beats heuristic on season window "
                "(heuristic_mae=%s ml_mae=%s n=%s). Set WNBA_TOTALS_ML_ENABLED=1 "
                "on API + celery-worker to promote.",
                season.get("heuristic_mae"),
                season.get("ml_mae"),
                season.get("ml_games"),
            )
        return {
            "status": "ok",
            "windows_written": len(accuracy_rows),
            "windows": window_stats,
            "recommend_promote": recommend,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
