"""NBA spread + win-prob accuracy over rolling windows."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NBASpreadAccuracy,
    NBASpreadActuals,
    NBASpreadProjections,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.wnba._db_upsert import replace_matching
from app.services.etl.wnba.spreads_accuracy_tracker import _ats_covered

logger = logging.getLogger(__name__)

NBA_SEASON_START_MONTH = 10


def _season_start(today: date) -> date:
    year = today.year if today.month >= NBA_SEASON_START_MONTH else today.year - 1
    return date(year, NBA_SEASON_START_MONTH, 1)


def _compute_nba_window(db, start: date, end: date) -> dict:
    rows = (
        db.query(NBASpreadProjections, NBASpreadActuals)
        .join(
            NBASpreadActuals,
            (NBASpreadProjections.game_date == NBASpreadActuals.game_date)
            & (NBASpreadProjections.home_team_name == NBASpreadActuals.home_team_name)
            & (NBASpreadProjections.away_team_name == NBASpreadActuals.away_team_name),
        )
        .filter(NBASpreadProjections.game_date >= start)
        .filter(NBASpreadProjections.game_date <= end)
        .all()
    )
    if not rows:
        return {"mae": None, "ats": None, "brier": None, "buckets": None, "total": 0}

    margin_errs = []
    ats_hits = 0
    ats_attempts = 0
    brier_sum = 0.0
    buckets: dict[str, dict[str, int]] = {
        f"{i/10:.1f}-{(i+1)/10:.1f}": {"count": 0, "wins": 0} for i in range(10)
    }

    for proj, actual in rows:
        margin_errs.append(proj.projected_margin - actual.actual_margin)
        covered = _ats_covered(
            proj.recommendation, actual.actual_margin, proj.market_spread_home
        )
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
    bucket_list = [
        {
            "bucket": key,
            "count": b["count"],
            "actual_win_rate": (b["wins"] / b["count"]) if b["count"] else None,
        }
        for key, b in buckets.items()
    ]
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
    accuracy_rows: list[dict] = []
    try:
        for _label, start, end in windows:
            stats = _compute_nba_window(db, start, end)
            if stats["total"] == 0:
                continue
            accuracy_rows.append(
                {
                    "date_range_start": start,
                    "date_range_end": end,
                    "total_games": stats["total"],
                    "spread_mae": stats["mae"],
                    "ats_hit_rate": stats["ats"],
                    "win_prob_brier_score": stats["brier"],
                    "calibration_buckets": stats["buckets"],
                    "created_at": datetime.utcnow(),
                }
            )
        replace_matching(
            db,
            NBASpreadAccuracy,
            accuracy_rows,
            match_keys=["date_range_start", "date_range_end"],
        )
        db.commit()
        return {"status": "ok", "windows_written": len(accuracy_rows)}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
