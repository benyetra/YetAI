"""Compute WNBA totals projection accuracy over rolling windows.

Joins WNBATotalsProjections ↔ WNBATotalsActuals on (game_date, home_team_name,
away_team_name) and writes three rows per run to WNBATotalsAccuracy: last 7,
last 30, season-to-date.

Mirrors backend/app/services/etl/nba/totals_accuracy_tracker.py.
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
from app.services.etl.wnba._espn import now_eastern

logger = logging.getLogger(__name__)

WNBA_SEASON_START_MONTH = 5  # WNBA season starts May 1


def _season_start(today: date) -> date:
    return date(today.year, WNBA_SEASON_START_MONTH, 1)


def _compute_window(db, start: date, end: date) -> dict:
    """Return MAE, RMSE, directional_accuracy, total_games for the window."""
    rows = (
        db.query(WNBATotalsProjections, WNBATotalsActuals)
        .join(
            WNBATotalsActuals,
            (WNBATotalsProjections.game_date == WNBATotalsActuals.game_date)
            & (WNBATotalsProjections.home_team_name == WNBATotalsActuals.home_team_name)
            & (WNBATotalsProjections.away_team_name == WNBATotalsActuals.away_team_name),
        )
        .filter(WNBATotalsProjections.game_date >= start)
        .filter(WNBATotalsProjections.game_date <= end)
        .all()
    )
    if not rows:
        return {"mae": None, "rmse": None, "directional": None, "total": 0}

    errs = []
    correct_direction = 0
    counted_direction = 0
    for proj, actual in rows:
        err = proj.projected_total - actual.actual_total
        errs.append(err)
        if proj.market_total is not None:
            # Directional accuracy: did our pick (over/under vs market) hit?
            our_side_over = proj.projected_total > proj.market_total
            actual_over = actual.actual_total > proj.market_total
            if proj.projected_total != proj.market_total and actual.actual_total != proj.market_total:
                counted_direction += 1
                if our_side_over == actual_over:
                    correct_direction += 1

    mae = sum(abs(e) for e in errs) / len(errs)
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    directional = correct_direction / counted_direction if counted_direction else None
    return {"mae": mae, "rmse": rmse, "directional": directional, "total": len(rows)}


def run() -> dict:
    today = now_eastern().date()
    windows = [
        ("last_7", today - timedelta(days=7), today),
        ("last_30", today - timedelta(days=30), today),
        ("season", _season_start(today), today),
    ]
    db = SessionLocal()
    written = 0
    try:
        for label, start, end in windows:
            stats = _compute_window(db, start, end)
            if stats["total"] == 0:
                continue
            db.merge(WNBATotalsAccuracy(
                date_range_start=start,
                date_range_end=end,
                total_games=stats["total"],
                mean_absolute_error=stats["mae"],
                root_mean_square_error=stats["rmse"],
                directional_accuracy=stats["directional"],
                created_at=datetime.utcnow(),
            ))
            written += 1
        db.commit()
        return {"status": "ok", "windows_written": written}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
