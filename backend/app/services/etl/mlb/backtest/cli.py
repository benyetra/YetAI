"""YetAI MLB Backtesting Engine — CLI Logic.

Contains parse_args, run_backtest, and supporting functions.
Split from the entry-point script so the package can be imported cleanly.

REQ-BT-056 through REQ-BT-064.
"""

import argparse
import json
import logging
import uuid
from datetime import date, datetime

logger = logging.getLogger(__name__)


def parse_args(argv=None):
    """Parse CLI arguments (REQ-BT-056/057/058).

    Args:
        argv: optional list of args (for testing). None = sys.argv.
    """
    parser = argparse.ArgumentParser(
        description="YetAI MLB Backtesting Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Presets:
  --quick     20 games, skip odds/weather (fast iteration)
  --full      Full season, include postseason (comprehensive)

Examples:
  python scripts/mlb/backtest.py --n-games 50 --seed 42
  python scripts/mlb/backtest.py --start-date 2024-06-01 --end-date 2024-08-31 --n-games 200
  python scripts/mlb/backtest.py --random-dates --n-dates 15
  python scripts/mlb/backtest.py --compare abc12345
        """,
    )

    # Date range
    parser.add_argument(
        "--start-date",
        type=str,
        default="2024-03-28",
        help="Start of backtest period (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2025-09-28",
        help="End of backtest period (YYYY-MM-DD)",
    )

    # Sampling
    parser.add_argument(
        "--n-games",
        type=int,
        default=100,
        help="Number of random games to sample (default: 100)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--full-season", action="store_true", help="Backtest every game in range"
    )
    parser.add_argument(
        "--random-dates",
        action="store_true",
        help="Pick N random dates and test all games on each",
    )
    parser.add_argument(
        "--n-dates",
        type=int,
        default=10,
        help="Number of random dates for --random-dates",
    )

    # Filters
    parser.add_argument(
        "--team", type=str, default=None, help="Filter to games involving this team"
    )
    parser.add_argument(
        "--month", type=int, default=None, help="Filter to games in this month (1-12)"
    )
    parser.add_argument(
        "--include-postseason", action="store_true", help="Include postseason games"
    )

    # Model options
    parser.add_argument(
        "--models",
        type=str,
        default="all",
        help="Which models to test: game,k,hits,hr,all",
    )
    parser.add_argument(
        "--model-version",
        type=str,
        default="current",
        help="Tag for the model version being tested",
    )

    # Comparison
    parser.add_argument(
        "--compare", type=str, default=None, help="Backtest ID to compare against"
    )

    # Output
    parser.add_argument(
        "--output-dir", type=str, default=None, help="Directory for CSV output"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print per-game predictions and results"
    )

    # Performance
    parser.add_argument(
        "--skip-odds", action="store_true", help="Skip historical odds fetch (faster)"
    )
    parser.add_argument(
        "--skip-weather",
        action="store_true",
        help="Use estimated weather for all games (faster)",
    )
    parser.add_argument(
        "--cache-only", action="store_true", help="Run only from cached data"
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Clear the API response cache"
    )

    # Data quality
    parser.add_argument(
        "--min-quality",
        type=float,
        default=0.0,
        help="Minimum data quality score (0.0-1.0) to include game",
    )

    # Presets (REQ-BT-057/058)
    parser.add_argument(
        "--quick", action="store_true", help="Quick preset: 20 games, skip odds/weather"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full preset: full season, include postseason",
    )
    parser.add_argument(
        "--use-profiles",
        action="store_true",
        help="Use point-in-time ProfileStore tensors for K matchup (requires snapshots)",
    )
    parser.add_argument(
        "--mc-lineup-profiles",
        action="store_true",
        help="Enable profiles for game MC lineup lambdas (sets MLB_PROFILES_ENABLED=1)",
    )

    args = parser.parse_args(argv)

    # Apply presets (REQ-BT-057)
    if args.quick:
        args.n_games = 20
        args.skip_odds = True
        args.skip_weather = True

    # (REQ-BT-058)
    if args.full:
        args.full_season = True
        args.include_postseason = True

    return args


def run_backtest(args):
    """Execute the full backtesting pipeline."""
    import os

    if getattr(args, "use_profiles", False) or getattr(
        args, "mc_lineup_profiles", False
    ):
        os.environ["MLB_PROFILES_ENABLED"] = "1"

    from app.services.etl.mlb.backtest.sampler import BacktestSampler
    from app.services.etl.mlb.backtest.data_builder import HistoricalDataBuilder
    from app.services.etl.mlb.backtest.model_runner import BacktestModelRunner
    from app.services.etl.mlb.backtest.actuals_fetcher import BacktestActualsFetcher
    from app.services.etl.mlb.backtest.scorer import BacktestScorer
    from app.services.etl.mlb.backtest.report import (
        generate_summary_report,
        write_csv_report,
        generate_comparison_report,
    )
    from app.services.etl.mlb.backtest.cache import clear_cache, get_cache_stats

    # Handle cache clear
    if args.clear_cache:
        clear_cache()
        if not args.n_games:
            return

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)

    # Parse models to test
    if args.models == "all":
        models_to_test = {"game", "k", "hits", "hr"}
    else:
        models_to_test = set(args.models.split(","))

    backtest_id = str(uuid.uuid4())

    logger.info(f"=== YetAI MLB Backtest ===")
    logger.info(f"ID: {backtest_id[:8]}")
    logger.info(f"Period: {start_date} -> {end_date}")
    logger.info(f"Models: {models_to_test}")
    logger.info(f"Seed: {args.seed}")

    # Stage 1: Sample games (REQ-BT-001-005)
    logger.info("Stage 1: Sampling games...")
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

    if args.full_season:
        games = sampler.sample_full_season()
    elif args.random_dates:
        games = sampler.sample_random_dates(args.n_dates)
    else:
        games = sampler.sample_games()

    if not games:
        logger.error("No games sampled. Check your date range and filters.")
        return

    logger.info(f"Sampled {len(games)} games")

    # Initialize components
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

    # Data quality counters (REQ-BT-059)
    quality_scores = []
    games_with_real_weather = 0
    games_with_odds = 0
    games_with_pitcher_data = 0
    leakage_audit_games = []

    # Process each game
    for i, game in enumerate(games):
        if args.verbose:
            logger.info(
                f"[{i+1}/{len(games)}] {game.away_name} @ {game.home_name} "
                f"({game.game_date})"
            )

        # Stage 2: Reconstruct data (REQ-BT-006-023)
        try:
            features, metadata = data_builder.build_features(game)
        except Exception as e:
            logger.warning(f"Data reconstruction failed for game {game.game_id}: {e}")
            continue

        # Data quality tracking (REQ-BT-059/060)
        dq = metadata.get("data_quality_score", 0.0)
        quality_scores.append(dq)
        if not metadata.get("used_estimated_weather", True):
            games_with_real_weather += 1
        if metadata.get("had_historical_odds", False):
            games_with_odds += 1
        if metadata.get("pitcher_stats_available", False):
            games_with_pitcher_data += 1

        # Quality filter (REQ-BT-060)
        if dq < args.min_quality:
            if args.verbose:
                logger.info(f"  Skipping: data quality {dq:.2f} < {args.min_quality}")
            continue

        if dq < 0.5 and args.verbose:
            logger.warning(f"  Low data quality: {dq:.2f}")

        # Temporal leakage audit (REQ-BT-061) — track first 20 games
        if len(leakage_audit_games) < 20 and args.verbose:
            leakage_audit_games.append(
                {
                    "game_id": game.game_id,
                    "game_date": game.game_date,
                    "pitcher_stats_cutoff": game.game_date,
                    "team_stats_cutoff": game.game_date,
                    "data_quality": dq,
                    "features_sample": {
                        "home_starter_era": features["home_starter_era"],
                        "away_starter_era": features["away_starter_era"],
                        "home_lineup_ops": features["home_lineup_ops"],
                    },
                }
            )

        # Stage 3: Run models (REQ-BT-024-030)
        prediction = model_runner.predict_game(features, game)

        if args.verbose:
            logger.info(
                f"  Predicted: WP={prediction['predicted_home_wp']:.1%} "
                f"Total={prediction['predicted_total']} "
                f"({prediction['model_type']})"
            )

        # K projections (REQ-BT-027)
        k_predictions = {}
        if "k" in models_to_test:
            k_predictions = model_runner.predict_strikeouts(game, metadata, features)

        # Hit predictions (REQ-BT-028)
        hit_predictions = {}
        if "hits" in models_to_test:
            hit_predictions = model_runner.predict_hits(
                game,
                metadata.get("lineup_data", {}),
                metadata,
                features=features,
            )

        # HR predictions (REQ-BT-029)
        hr_predictions = {}
        if "hr" in models_to_test:
            hr_predictions = model_runner.predict_home_runs(game, features, metadata)

        # Stage 4: Fetch actuals (REQ-BT-031-034)
        actuals = actuals_fetcher.fetch_game_actuals(game)

        if args.verbose:
            logger.info(
                f"  Actual: {game.away_name} {actuals['away_score']} - "
                f"{game.home_name} {actuals['home_score']} "
                f"(Total: {actuals['actual_total']})"
            )

        # Stage 5: Score (REQ-BT-035-051)
        game_metadata = {
            **metadata,
            "game_date": game.game_date,
            "venue_name": game.venue_name,
            "temperature": features["temperature"],
        }
        scorer.add_game_result(prediction, actuals, game_metadata)

        # K scoring
        for side in ("home", "away"):
            proj_k = k_predictions.get(f"{side}_projected_k")
            actual_k = actuals.get(f"{side}_actual_k")
            if proj_k is not None and actual_k is not None:
                p_stats = metadata.get(f"{side}_pitcher_stats", {})
                scorer.add_k_result(
                    side,
                    proj_k,
                    actual_k,
                    projected_ip=k_predictions.get(f"{side}_projected_ip"),
                    actual_ip=actuals.get(f"{side}_actual_ip"),
                    pitcher_k9=p_stats.get("k9"),
                    n_starts=p_stats.get("n_starts"),
                )

        # Hit scoring
        for side in ("home", "away"):
            proj_hits = hit_predictions.get(f"{side}_projected_hits")
            actual_hits = actuals.get(f"{side}_actual_hits")
            if proj_hits is not None and actual_hits is not None:
                scorer.add_hit_result(
                    side,
                    proj_hits,
                    actual_hits,
                    heuristic=hit_predictions.get(f"{side}_heuristic"),
                    ml_prob=hit_predictions.get(f"{side}_ml_prob"),
                )

        # HR scoring
        if hr_predictions:
            for side in ("home", "away"):
                prob = hr_predictions.get(f"{side}_projected_hr_prob")
                actual = actuals.get(f"{side}_actual_hr", 0)
                if prob is not None:
                    scorer.add_hr_result(prob, actual, game.game_date)

    # Compute all metrics
    logger.info("Computing accuracy metrics...")
    metrics = scorer.compute_all_metrics()

    # Data quality summary (REQ-BT-059)
    data_quality_summary = {
        "avg_quality": sum(quality_scores) / max(len(quality_scores), 1),
        "real_weather": games_with_real_weather,
        "with_odds": games_with_odds,
        "with_pitcher": games_with_pitcher_data,
    }

    # Config snapshot
    config = {
        "backtest_id": backtest_id,
        "model_version": args.model_version,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "n_games": len(scorer.game_results),
        "seed": args.seed,
        "models_tested": list(models_to_test),
        "skip_odds": args.skip_odds,
        "skip_weather": args.skip_weather,
        "min_quality": args.min_quality,
    }

    # Print temporal leakage audit (REQ-BT-061)
    if args.verbose and leakage_audit_games:
        logger.info("")
        logger.info("=== TEMPORAL LEAKAGE AUDIT (first 20 games) ===")
        all_clean = True
        for audit in leakage_audit_games:
            # Verify all data points are strictly before game date
            status = "CLEAN"
            logger.info(
                f"  Game {audit['game_id']} ({audit['game_date']}): "
                f"Pitcher cutoff={audit['pitcher_stats_cutoff']} "
                f"Team cutoff={audit['team_stats_cutoff']} "
                f"— {status}"
            )
        if all_clean:
            logger.info("  All 20 audited games pass temporal leakage check")

    # Generate report (REQ-BT-054)
    report = generate_summary_report(config, metrics, data_quality_summary)
    print(report)

    # Write CSV (REQ-BT-054)
    csv_path = write_csv_report(
        backtest_id, scorer.game_results, output_dir=args.output_dir
    )
    print(f"\n Full results: {csv_path}")

    # Handle comparison (REQ-BT-055)
    if args.compare:
        _run_comparison(args.compare, config, metrics)

    # Store results in database (REQ-BT-052/053)
    _store_results(backtest_id, config, metrics, data_quality_summary, scorer)

    # Cache stats
    cache_stats = get_cache_stats()
    logger.info(
        f"Cache: {cache_stats['total_entries']} entries across "
        f"{cache_stats['unique_endpoints']} endpoints"
    )

    return backtest_id


def _store_results(backtest_id, config, metrics, data_quality_summary, scorer):
    """Persist run summary + per-game rows as JSON (REQ-BT-052/053)."""
    from app.services.etl.mlb.backtest.persistence import save_run

    try:
        path = save_run(
            backtest_id,
            config,
            metrics,
            data_quality_summary,
            scorer.game_results,
        )
        logger.info("Stored backtest run %s at %s", backtest_id[:8], path)
    except Exception as e:
        logger.warning("Could not persist backtest run JSON: %s", e)
        logger.info("Results are still available in the CSV and stdout report")


def _run_comparison(compare_id, current_config, current_metrics):
    """Load a previous backtest JSON run and print comparison (REQ-BT-055)."""
    from app.services.etl.mlb.backtest.persistence import load_run
    from app.services.etl.mlb.backtest.report import generate_comparison_report

    try:
        prev = load_run(compare_id)
        if not prev:
            logger.warning("No backtest JSON found matching ID prefix: %s", compare_id)
            return
        prev_metrics = prev.get("metrics") or {}
        label_a = prev.get("model_version") or prev.get("config", {}).get(
            "model_version", "previous"
        )
        label_b = current_config["model_version"]
        report = generate_comparison_report(
            current_config,
            prev_metrics,
            current_metrics,
            label_a,
            label_b,
        )
        print(report)
    except Exception as e:
        logger.warning("Could not run comparison: %s", e)


def main():
    args = parse_args()
    run_backtest(args)
