"""Compute WNBA spread + win-prob accuracy over rolling windows.

NEW — no NBA equivalent. Joins WNBASpreadProjections ↔ WNBASpreadActuals on
(game_date, home_team_name, away_team_name) and produces:

- spread_mae: mean abs error of projected_margin vs actual_margin
- ats_hit_rate: of picks (recommendation != NO_PLAY), % that covered
- win_prob_brier_score: mean of (home_win_prob - home_won_int)^2
- calibration_buckets: per 10% bucket of home_win_prob, actual win rate

Writes three rows per run: last 7, last 30, season-to-date.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBASpreadAccuracy,
    WNBASpreadActuals,
    WNBASpreadProjections,
)
from app.services.etl.wnba._espn import now_eastern

logger = logging.getLogger(__name__)

WNBA_SEASON_START_MONTH = 5


def _season_start(today: date) -> date:
    return date(today.year, WNBA_SEASON_START_MONTH, 1)


def _ats_covered(recommendation: str, actual_margin: int, market_spread_home: float) -> bool | None:
    """Return True/False if pick covered; None for pushes or no-play."""
    if recommendation == "NO_PLAY" or market_spread_home is None:
        return None
    # home covers when actual_margin > -market_spread_home (e.g., spread_home=-5 → home must win by >5)
    # away covers when actual_margin < -market_spread_home
    threshold = -market_spread_home
    if actual_margin == threshold:
        return None  # push
    if recommendation == "HOME":
        return actual_margin > threshold
    if recommendation == "AWAY":
        return actual_margin < threshold
    return None


def _compute_window(db, start: date, end: date) -> dict:
    rows = (
        db.query(WNBASpreadProjections, WNBASpreadActuals)
        .join(
            WNBASpreadActuals,
            (WNBASpreadProjections.game_date == WNBASpreadActuals.game_date)
            & (WNBASpreadProjections.home_team_name == WNBASpreadActuals.home_team_name)
            & (WNBASpreadProjections.away_team_name == WNBASpreadActuals.away_team_name),
        )
        .filter(WNBASpreadProjections.game_date >= start)
        .filter(WNBASpreadProjections.game_date <= end)
        .all()
    )
    if not rows:
        return {"mae": None, "ats": None, "brier": None, "buckets": None, "total": 0}

    margin_errs = []
    ats_hits = 0
    ats_attempts = 0
    brier_sum = 0.0
    # 10 buckets covering [0.0, 1.0]
    buckets: dict[str, dict[str, int]] = {
        f"{i/10:.1f}-{(i+1)/10:.1f}": {"count": 0, "wins": 0} for i in range(10)
    }

    for proj, actual in rows:
        margin_errs.append(proj.projected_margin - actual.actual_margin)

        covered = _ats_covered(proj.recommendation, actual.actual_margin, proj.market_spread_home)
        if covered is not None:
            ats_attempts += 1
            if covered:
                ats_hits += 1

        wp = proj.home_win_prob
        won = 1 if actual.home_won else 0
        brier_sum += (wp - won) ** 2

        bucket_idx = min(int(wp * 10), 9)
        bucket_key = f"{bucket_idx/10:.1f}-{(bucket_idx+1)/10:.1f}"
        buckets[bucket_key]["count"] += 1
        if actual.home_won:
            buckets[bucket_key]["wins"] += 1

    mae = sum(abs(e) for e in margin_errs) / len(margin_errs)
    ats = ats_hits / ats_attempts if ats_attempts else None
    brier = brier_sum / len(rows)
    # Pack buckets with actual win rate
    bucket_list = []
    for key, b in buckets.items():
        bucket_list.append({
            "bucket": key,
            "count": b["count"],
            "actual_win_rate": (b["wins"] / b["count"]) if b["count"] else None,
        })

    return {
        "mae": mae,
        "ats": ats,
        "brier": brier,
        "buckets": bucket_list,
        "total": len(rows),
    }


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
        for _label, start, end in windows:
            stats = _compute_window(db, start, end)
            if stats["total"] == 0:
                continue
            db.merge(WNBASpreadAccuracy(
                date_range_start=start,
                date_range_end=end,
                total_games=stats["total"],
                spread_mae=stats["mae"],
                ats_hit_rate=stats["ats"],
                win_prob_brier_score=stats["brier"],
                calibration_buckets=stats["buckets"],
                created_at=datetime.utcnow(),
            ))
            written += 1
        db.commit()
        return {"status": "ok", "windows_written": written}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
