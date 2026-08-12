#!/usr/bin/env python3
"""Audit QB pass-yds prop-line coverage on pred_qb_actuals (no Odds spend).

Reports how many rows already have ``ou_line``, how many the historical index
can fill, and what remains missing — useful before/after a 2025 Odds backfill.

Usage::

    export DATABASE_URL=...
    PYTHONPATH=. python scripts/nfl_pass_yds_line_coverage.py \\
      --season-start 2025-09-01 --season-end 2026-02-15
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit pass-yds line coverage")
    parser.add_argument("--season-start", type=str, default="2025-09-01")
    parser.add_argument("--season-end", type=str, default="2026-02-15")
    args = parser.parse_args()
    if not os.getenv("DATABASE_URL", "").strip():
        print(json.dumps({"status": "error", "error": "DATABASE_URL required"}))
        return 2

    from app.core.database import SessionLocal
    from app.models.predictions_models import QBActuals, QBPredictions
    from app.services.etl.nfl.historical_pass_yds_odds import (
        load_lines_index,
        lookup_pass_yds_line,
    )

    start = date.fromisoformat(args.season_start)
    end = date.fromisoformat(args.season_end)
    idx = load_lines_index()
    index_seasons = sorted(
        {int(r.get("season") or 0) for r in (idx.get("lines") or []) if r.get("season")}
    )

    session = SessionLocal()
    try:
        rows = (
            session.query(QBActuals)
            .filter(QBActuals.game_date >= start, QBActuals.game_date <= end)
            .order_by(QBActuals.season, QBActuals.week)
            .all()
        )
        sources: Counter[str] = Counter()
        missing_weeks: Counter[int] = Counter()
        missing_sample: list[dict[str, object]] = []
        for r in rows:
            pred = (
                session.query(QBPredictions)
                .filter(
                    QBPredictions.qb_player_id == r.qb_player_id,
                    QBPredictions.season == r.season,
                    QBPredictions.week == r.week,
                )
                .first()
            )
            if pred is None:
                pred = (
                    session.query(QBPredictions)
                    .filter(
                        QBPredictions.qb_player_name == r.qb_player_name,
                        QBPredictions.season == r.season,
                        QBPredictions.week == r.week,
                    )
                    .first()
                )
            if pred is not None and pred.ou_line is not None:
                sources["ou_line"] += 1
                continue
            hist = lookup_pass_yds_line(
                season=int(r.season),
                week=int(r.week),
                player_name=str(r.qb_player_name or ""),
                team_abbr=str(getattr(r, "team_name", "") or ""),
                index=idx,
            )
            if hist is not None:
                sources["historical_index"] += 1
                continue
            sources["none"] += 1
            missing_weeks[int(r.week)] += 1
            if len(missing_sample) < 25:
                missing_sample.append(
                    {
                        "season": int(r.season),
                        "week": int(r.week),
                        "qb": r.qb_player_name,
                        "team": getattr(r, "team_name", None),
                        "has_prediction_row": pred is not None,
                    }
                )
    finally:
        session.close()

    n = sum(sources.values())
    real = sources["ou_line"] + sources["historical_index"]
    report = {
        "status": "ok",
        "season_start": str(start),
        "season_end": str(end),
        "rows": n,
        "real_n": real,
        "real_rate": round(real / n, 4) if n else 0.0,
        "missing_n": sources["none"],
        "sources": dict(sources),
        "index_seasons": index_seasons,
        "index_lines": len(idx.get("lines") or []),
        "missing_by_week": dict(sorted(missing_weeks.items())),
        "missing_sample": missing_sample,
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
