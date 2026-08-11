#!/usr/bin/env python3
"""Train anytime-TD residual GBM calibrator from walk-forward graded rows.

Writes ``backend/models/nfl/anytime_td_residual_gbm.pkl`` (+ metadata JSON).

Examples::

    cd backend
    PYTHONPATH=. python scripts/nfl_anytime_td_train_calibration.py
    PYTHONPATH=. python scripts/nfl_anytime_td_train_calibration.py --seasons 2023,2024,2025
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--seasons",
        type=str,
        default=None,
        help="Comma-separated seasons (default: auto-detect published weekly)",
    )
    p.add_argument("--start-week", type=int, default=2)
    p.add_argument("--end-week", type=int, default=18)
    p.add_argument(
        "--model-path",
        type=Path,
        default=BACKEND_ROOT / "models" / "nfl" / "anytime_td_residual_gbm.pkl",
    )
    p.add_argument(
        "--meta-path",
        type=Path,
        default=BACKEND_ROOT / "models" / "nfl" / "anytime_td_residual_gbm.json",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    from app.services.etl.nfl.anytime_td_backtest import (
        grade_week_from_weekly_records,
        resolve_walk_forward_seasons,
    )
    from app.services.etl.nfl.anytime_td_calibration import (
        fit_residual_gbm,
        save_calibration_artifact,
    )
    from app.services.etl.nfl.anytime_td_features import (
        load_weekly_records_with_fallback,
    )
    from app.services.etl.nfl.anytime_td_pbp import load_pbp_records_nflverse

    if args.seasons:
        seasons = tuple(int(s.strip()) for s in args.seasons.split(",") if s.strip())
    else:
        seasons = resolve_walk_forward_seasons(load_live=True)

    train_rows: list[dict] = []
    for season in seasons:
        records, _src = load_weekly_records_with_fallback(int(season), max_lookback=0)
        if not records:
            logger.warning("skip season %s — no weekly", season)
            continue
        pbp = load_pbp_records_nflverse(int(season))
        for week in range(args.start_week, args.end_week + 1):
            graded = grade_week_from_weekly_records(
                int(season),
                int(week),
                weekly_records=records,
                pbp_records=pbp,
            )
            train_rows.extend(graded)
        logger.info("season %s cumulative train rows=%s", season, len(train_rows))

    model = fit_residual_gbm(train_rows)
    if model is None:
        logger.error("failed to fit residual GBM (n=%s)", len(train_rows))
        return 1

    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_train": len(train_rows),
        "seasons": list(seasons),
        "start_week": args.start_week,
        "end_week": args.end_week,
        "positive_rate": (
            sum(1 for r in train_rows if r.get("scored_anytime_td")) / len(train_rows)
            if train_rows
            else 0.0
        ),
    }
    mpath, jpath = save_calibration_artifact(
        model,
        metadata=meta,
        model_path=args.model_path,
        meta_path=args.meta_path,
    )
    logger.info("wrote %s and %s (n_train=%s)", mpath, jpath, len(train_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
