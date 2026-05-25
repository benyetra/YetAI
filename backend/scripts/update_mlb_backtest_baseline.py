#!/usr/bin/env python3
"""Refresh committed MLB quick-backtest CI baseline (requires network).

Runs ``scripts/mlb_backtest.py --quick``, summarizes game/hit metrics, and writes
``tests/fixtures/mlb_backtest_quick_baseline.json``. Use after an intentional model
change that should become the new regression reference.

Example::

    cd backend
    PYTHONPATH=. python scripts/update_mlb_backtest_baseline.py
    pytest tests/test_mlb_backtest_regression.py -q
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE_PATH = (
    BACKEND_ROOT / "tests" / "fixtures" / "mlb_backtest_quick_baseline.json"
)


def _run_quick_backtest(seed: int) -> dict:
    from app.services.etl.mlb.backtest.cli import parse_args
    from app.services.etl.mlb.backtest.scorer import BacktestScorer

    argv = ["--quick", "--seed", str(seed)]
    args = parse_args(argv)

    from app.services.etl.mlb.backtest.actuals_fetcher import BacktestActualsFetcher
    from app.services.etl.mlb.backtest.data_builder import HistoricalDataBuilder
    from app.services.etl.mlb.backtest.model_runner import BacktestModelRunner
    from app.services.etl.mlb.backtest.sampler import BacktestSampler

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    models_to_test = (
        {"game", "k", "hits", "hr"}
        if args.models == "all"
        else set(args.models.split(","))
    )

    sampler = BacktestSampler(
        start_date=start_date,
        end_date=end_date,
        n_games=args.n_games,
        seed=args.seed,
        team=args.team,
        month=args.month,
        include_postseason=args.include_postseason,
        cache_only=args.cache_only,
    )
    games = sampler.sample_games()
    if not games:
        raise RuntimeError("No games sampled; cannot update baseline.")

    data_builder = HistoricalDataBuilder(
        cache_only=args.cache_only,
        skip_weather=args.skip_weather,
        skip_odds=args.skip_odds,
    )
    model_runner = BacktestModelRunner(
        model_version=args.model_version,
        models_to_test=models_to_test,
    )
    actuals_fetcher = BacktestActualsFetcher(cache_only=args.cache_only)
    scorer = BacktestScorer()

    for game in games:
        try:
            features, metadata = data_builder.build_features(game)
        except Exception as exc:
            logger.warning("Skip game %s: %s", game.game_id, exc)
            continue
        if metadata.get("data_quality_score", 0.0) < args.min_quality:
            continue
        prediction = model_runner.predict_game(features, game)
        actuals = actuals_fetcher.fetch_game_actuals(game)
        game_metadata = {
            **metadata,
            "game_date": game.game_date,
            "venue_name": game.venue_name,
            "temperature": features["temperature"],
        }
        scorer.add_game_result(prediction, actuals, game_metadata)
        if "hits" in models_to_test:
            hit_predictions = model_runner.predict_hits(
                game,
                metadata.get("lineup_data", {}),
                metadata,
                features=features,
            )
            for side in ("home", "away"):
                proj = hit_predictions.get(f"{side}_projected_hits")
                actual_h = actuals.get(f"{side}_actual_hits")
                if proj is not None and actual_h is not None:
                    scorer.add_hit_result(
                        side,
                        proj,
                        actual_h,
                        heuristic=hit_predictions.get(f"{side}_heuristic"),
                        ml_prob=hit_predictions.get(f"{side}_ml_prob"),
                    )

    if not scorer.game_results:
        raise RuntimeError("No scored games; cannot update baseline.")

    from app.services.etl.mlb.backtest.metrics import summarize_backtest_metrics

    return summarize_backtest_metrics(scorer)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Baseline JSON path (default: tests/fixtures/...)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Backtest random seed")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print metrics JSON to stdout without writing file",
    )
    args = parser.parse_args(argv)

    logger.info("Running quick backtest (network required)...")
    metrics = _run_quick_backtest(args.seed)
    payload = {
        "description": (
            "MLB quick backtest (--quick, 20 games, skip odds/weather). "
            "Refresh via scripts/update_mlb_backtest_baseline.py after intentional "
            "model changes."
        ),
        "updated_at": date.today().isoformat(),
        "preset": "quick",
        "seed": args.seed,
        "metrics": metrics,
    }
    text = json.dumps(payload, indent=2) + "\n"
    if args.dry_run:
        print(text)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    logger.info("Wrote baseline to %s", args.output)
    logger.info("Metrics: %s", metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
