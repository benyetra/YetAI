#!/usr/bin/env python
"""Comprehensive PRD verification for the MLB Backtesting Engine.

Tests all 64 requirements (REQ-BT-001 through REQ-BT-064) from
YetiBets_MLB_Backtesting_PRD.md via structural, import, and functional checks.
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import ast
import inspect
import importlib
import textwrap

passed = 0
failed = 0
warnings = 0


def check(label, condition, note=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        extra = f" — {note}" if note else ""
        print(f"  FAIL  {label}{extra}")


def warn(label, note=""):
    global warnings
    warnings += 1
    extra = f" — {note}" if note else ""
    print(f"  WARN  {label}{extra}")


# ---------------------------------------------------------------------------
# §6. File Structure
# ---------------------------------------------------------------------------
print("\n=== §6. FILE STRUCTURE ===")
base = os.path.join(os.path.dirname(__file__))
expected_files = [
    "backtest.py",
    "backtest/__init__.py",
    "backtest/cli.py",
    "backtest/sampler.py",
    "backtest/data_builder.py",
    "backtest/model_runner.py",
    "backtest/actuals_fetcher.py",
    "backtest/scorer.py",
    "backtest/cache.py",
    "backtest/report.py",
    "backtest/models.py",
    "backtest_results/.gitkeep",
]
for f in expected_files:
    path = os.path.join(base, f)
    check(f"File exists: {f}", os.path.exists(path), f"Missing: {path}")

# ---------------------------------------------------------------------------
# §5.1 Game Sampler (REQ-BT-001 through REQ-BT-005)
# ---------------------------------------------------------------------------
print("\n=== §5.1 GAME SAMPLER ===")
from app.services.etl.mlb.backtest.sampler import BacktestSampler, BacktestGame
from dataclasses import fields as dc_fields

# REQ-BT-001: BacktestSampler accepts date range, sample size, seed, filters
init_params = inspect.signature(BacktestSampler.__init__).parameters
check("REQ-BT-001a: start_date param", "start_date" in init_params)
check("REQ-BT-001b: end_date param", "end_date" in init_params)
check("REQ-BT-001c: n_games param", "n_games" in init_params)
check("REQ-BT-001d: seed param", "seed" in init_params)
check("REQ-BT-001e: team filter", "team" in init_params)
check("REQ-BT-001f: month filter", "month" in init_params)

# REQ-BT-002: schedule fetch and filter (check source for statsapi.schedule call)
src = inspect.getsource(BacktestSampler)
check("REQ-BT-002a: uses statsapi.schedule", "schedule(" in src)
check("REQ-BT-002b: filters Final games", "'Final'" in src or '"Final"' in src)
check("REQ-BT-002c: include_postseason param", "include_postseason" in init_params)

# REQ-BT-003: seeded random.sample
check("REQ-BT-003: seeded random sample", "random.Random" in src or "Random(" in src)

# REQ-BT-004: BacktestGame dataclass fields
bg_fields = {f.name for f in dc_fields(BacktestGame)}
required_fields = {
    "game_id",
    "game_date",
    "home_name",
    "away_name",
    "home_id",
    "away_id",
    "venue_name",
    "home_score",
    "away_score",
}
for f in required_fields:
    check(f"REQ-BT-004: BacktestGame.{f}", f in bg_fields)

# REQ-BT-005: full-season and random-dates modes
check(
    "REQ-BT-005a: sample_full_season()", hasattr(BacktestSampler, "sample_full_season")
)
check(
    "REQ-BT-005b: sample_random_dates()",
    hasattr(BacktestSampler, "sample_random_dates"),
)

# ---------------------------------------------------------------------------
# §5.2 Data Reconstructor (REQ-BT-006 through REQ-BT-023)
# ---------------------------------------------------------------------------
print("\n=== §5.2 DATA RECONSTRUCTOR ===")
from app.services.etl.mlb.backtest.data_builder import HistoricalDataBuilder

hdb_src = inspect.getsource(HistoricalDataBuilder)

# REQ-BT-006: pitcher game log reconstruction
check(
    "REQ-BT-006: pitcher stats reconstruction", "_reconstruct_pitcher_stats" in hdb_src
)

# REQ-BT-007: game log filtering by date
check(
    "REQ-BT-007: date filtering in pitcher stats",
    "game_date" in hdb_src and ("date" in hdb_src.lower()),
)

# REQ-BT-008: league-average defaults
check("REQ-BT-008a: default ERA", "4.50" in hdb_src or "4.5" in hdb_src)
check("REQ-BT-008b: default K/9", "8.0" in hdb_src)
check("REQ-BT-008c: default WHIP", "1.35" in hdb_src)

# REQ-BT-009: team stats reconstruction
check("REQ-BT-009: team hitting reconstruction", "_reconstruct_team_hitting" in hdb_src)
check(
    "REQ-BT-009b: team pitching reconstruction", "_reconstruct_team_pitching" in hdb_src
)

# REQ-BT-010: early-season blending
check(
    "REQ-BT-010: early-season blending formula",
    "games + 20" in hdb_src or "(games + 20)" in hdb_src,
)

# REQ-BT-011: lineup from boxscore
check("REQ-BT-011: lineup reconstruction", "_reconstruct_lineup" in hdb_src)
check("REQ-BT-011b: boxscore_data usage", "boxscore_data" in hdb_src)

# REQ-BT-012: batter stats (covered by lineup reconstruction)
check(
    "REQ-BT-012: batter stats in lineup", "ops" in hdb_src.lower() or "OPS" in hdb_src
)

# REQ-BT-013: bullpen fatigue
check(
    "REQ-BT-013: bullpen fatigue reconstruction",
    "_reconstruct_bullpen_fatigue" in hdb_src,
)

# REQ-BT-014: domed stadium weather
check(
    "REQ-BT-014: domed stadium detection",
    "dome" in hdb_src.lower() or "Tropicana" in hdb_src or "DOMED" in hdb_src,
)

# REQ-BT-015: weather reconstruction
check("REQ-BT-015: weather reconstruction", "_reconstruct_weather" in hdb_src)

# REQ-BT-016: weather_run_adj
check("REQ-BT-016: weather run adjustment", "weather_run_adj" in hdb_src)

# REQ-BT-017: park factors
check(
    "REQ-BT-017: park factor lookup",
    "park_factor" in hdb_src or "VENUE_PARK_FACTORS" in hdb_src,
)

# REQ-BT-018: historical odds
check(
    "REQ-BT-018: historical odds fetch",
    "_fetch_historical_odds" in hdb_src or "historical" in hdb_src.lower(),
)

# REQ-BT-019: odds unavailable handling
check(
    "REQ-BT-019: odds unavailable flag",
    "had_historical_odds" in hdb_src or "market_odds_available" in hdb_src,
)

# REQ-BT-020: TTOP
check("REQ-BT-020: TTOP reconstruction", "ttop" in hdb_src.lower())

# REQ-BT-021: umpire effects
check(
    "REQ-BT-021: umpire reconstruction",
    "_reconstruct_umpire" in hdb_src or "umpire" in hdb_src.lower(),
)

# REQ-BT-022: travel fatigue
check(
    "REQ-BT-022: travel fatigue reconstruction",
    "_reconstruct_travel" in hdb_src or "travel" in hdb_src.lower(),
)

# REQ-BT-023: pitcher quality
check(
    "REQ-BT-023: pitcher quality score",
    "pitcher_quality" in hdb_src.lower() or "_compute_pitcher_quality" in hdb_src,
)

# ---------------------------------------------------------------------------
# §5.3 Model Runner (REQ-BT-024 through REQ-BT-030)
# ---------------------------------------------------------------------------
print("\n=== §5.3 MODEL RUNNER ===")
from app.services.etl.mlb.backtest.model_runner import BacktestModelRunner

mr_src = inspect.getsource(BacktestModelRunner)

# REQ-BT-024: FEATURE_COLS format
check("REQ-BT-024: FEATURE_COLS import", "FEATURE_COLS" in mr_src)

# REQ-BT-025: heuristic models
check("REQ-BT-025a: heuristic win prob", "predict_win_probability_heuristic" in mr_src)
check("REQ-BT-025b: heuristic total", "predict_total_runs_heuristic" in mr_src)

# REQ-BT-026: ensemble predictions
check(
    "REQ-BT-026: ensemble model support",
    "ensemble" in mr_src.lower() or "predict_proba" in mr_src,
)

# REQ-BT-027: K projections
check(
    "REQ-BT-027: predict_strikeouts()",
    hasattr(BacktestModelRunner, "predict_strikeouts"),
)

# REQ-BT-028: hit predictions
check("REQ-BT-028: predict_hits()", hasattr(BacktestModelRunner, "predict_hits"))

# REQ-BT-029: HR predictions
check(
    "REQ-BT-029: predict_home_runs()", hasattr(BacktestModelRunner, "predict_home_runs")
)

# REQ-BT-030: Venn-Abers calibration
check("REQ-BT-030: Venn-Abers support", "VennAbers" in mr_src or "venn_abers" in mr_src)

# ---------------------------------------------------------------------------
# §5.4 Actuals Fetcher (REQ-BT-031 through REQ-BT-034)
# ---------------------------------------------------------------------------
print("\n=== §5.4 ACTUALS FETCHER ===")
from app.services.etl.mlb.backtest.actuals_fetcher import BacktestActualsFetcher

af_src = inspect.getsource(BacktestActualsFetcher)

# REQ-BT-031: final scores
check(
    "REQ-BT-031: fetch_game_actuals()",
    hasattr(BacktestActualsFetcher, "fetch_game_actuals"),
)
check(
    "REQ-BT-031b: scores extraction", "home_score" in af_src and "away_score" in af_src
)

# REQ-BT-032: pitcher K and IP
check("REQ-BT-032: pitcher actuals", "_extract_pitcher_actuals" in af_src)
check("REQ-BT-032b: strikeout fields", "actual_k" in af_src)

# REQ-BT-033: batter hits
check("REQ-BT-033: batter actuals", "_extract_batter_actuals" in af_src)

# REQ-BT-034: home runs
check("REQ-BT-034: HR extraction", "_extract_hr_actuals" in af_src)

# ---------------------------------------------------------------------------
# §5.5 Accuracy Scorer (REQ-BT-035 through REQ-BT-051)
# ---------------------------------------------------------------------------
print("\n=== §5.5 ACCURACY SCORER ===")
from app.services.etl.mlb.backtest.scorer import BacktestScorer

sc = BacktestScorer()
sc_src = inspect.getsource(BacktestScorer)

# REQ-BT-035: Brier Score
check("REQ-BT-035: Brier Score computation", "brier_score" in sc_src.lower())

# REQ-BT-036: ML accuracy
check("REQ-BT-036: ML accuracy", "ml_accuracy" in sc_src)

# REQ-BT-037: O/U accuracy
check("REQ-BT-037: O/U accuracy", "ou_accuracy" in sc_src)

# REQ-BT-038: Total MAE
check("REQ-BT-038: Total MAE", "total_mae" in sc_src)

# REQ-BT-039: Run line accuracy
check("REQ-BT-039: Run line accuracy", "run_line" in sc_src)

# REQ-BT-040: Calibration table
check("REQ-BT-040: Calibration", "calibration" in sc_src.lower())

# REQ-BT-041: K MAE
check("REQ-BT-041: K MAE", "k_mae" in sc_src)

# REQ-BT-042: K gold standard
check("REQ-BT-042: K gold standard", "gold_standard" in sc_src)

# REQ-BT-043: vs-line accuracy (in K metrics or report)
check("REQ-BT-043: vs-line metric", "k_vs_line" in sc_src or "vs_line" in sc_src)

# REQ-BT-044: offset effectiveness
check(
    "REQ-BT-044: offset effectiveness",
    "offset" in sc_src.lower() or "n_starts" in sc_src,
)

# REQ-BT-045: hit accuracy
check(
    "REQ-BT-045: hit prediction metrics",
    "hit_mae" in sc_src or "hit_accuracy" in sc_src,
)

# REQ-BT-046: HR top-10 hit rate
check("REQ-BT-046: HR top-10", "top10" in sc_src.lower() or "top_10" in sc_src)

# REQ-BT-047: HR AUC-ROC
check("REQ-BT-047: HR AUC-ROC", "auc" in sc_src.lower())

# REQ-BT-048: edge vs market / simulated ROI
check("REQ-BT-048: simulated ROI", "simulated_roi" in sc_src)

# REQ-BT-049: model vs market Brier
check(
    "REQ-BT-049: model vs market Brier",
    "model_vs_market" in sc_src or "market_brier" in sc_src,
)

# REQ-BT-050: segmented analysis (month, temp, quality)
check("REQ-BT-050a: by month", "by_month" in sc_src)
check(
    "REQ-BT-050b: by temperature", "by_temperature" in sc_src or "temperature" in sc_src
)

# REQ-BT-051: K by tier
check("REQ-BT-051: K by K/9 tier", "k9_tier" in sc_src or "by_k9" in sc_src)

# ---------------------------------------------------------------------------
# §5.6 Storage & Reporting (REQ-BT-052 through REQ-BT-055)
# ---------------------------------------------------------------------------
print("\n=== §5.6 STORAGE & REPORTING ===")
from app.services.etl.mlb.backtest.models import BacktestResults, BacktestGameResult

# REQ-BT-052: BacktestResults model fields
check("REQ-BT-052a: BacktestResults exists", BacktestResults is not None)
bt_cols = {c.name for c in BacktestResults.__table__.columns}
for col in [
    "id",
    "run_date",
    "model_version",
    "date_range_start",
    "date_range_end",
    "n_games",
    "seed",
    "brier_score",
    "ml_accuracy",
    "ou_accuracy",
    "total_mae",
    "k_mae",
    "k_gold_standard_rate",
    "hr_top10_hit_rate",
    "config_json",
    "results_json",
]:
    check(f"REQ-BT-052: BacktestResults.{col}", col in bt_cols, f"missing column {col}")

# REQ-BT-053: BacktestGameResult model fields
check("REQ-BT-053a: BacktestGameResult exists", BacktestGameResult is not None)
bgr_cols = {c.name for c in BacktestGameResult.__table__.columns}
for col in [
    "backtest_id",
    "game_id",
    "game_date",
    "home_team",
    "away_team",
    "predicted_home_wp",
    "actual_winner",
    "predicted_total",
    "actual_total",
    "ml_correct",
    "total_correct",
    "data_quality_score",
]:
    check(
        f"REQ-BT-053: BacktestGameResult.{col}",
        col in bgr_cols,
        f"missing column {col}",
    )

# REQ-BT-054: report generation
from app.services.etl.mlb.backtest.report import (
    generate_summary_report,
    write_csv_report,
)

check("REQ-BT-054a: generate_summary_report()", callable(generate_summary_report))
check("REQ-BT-054b: write_csv_report()", callable(write_csv_report))

# REQ-BT-055: comparison report
from app.services.etl.mlb.backtest.report import generate_comparison_report

check("REQ-BT-055: generate_comparison_report()", callable(generate_comparison_report))

# ---------------------------------------------------------------------------
# §5.7 CLI Interface (REQ-BT-056 through REQ-BT-058)
# ---------------------------------------------------------------------------
print("\n=== §5.7 CLI INTERFACE ===")
from app.services.etl.mlb.backtest.cli import parse_args, run_backtest, main

# REQ-BT-056: all CLI flags
args = parse_args([])  # Parse defaults
check("REQ-BT-056a: parse_args()", args is not None)
for flag in [
    "start_date",
    "end_date",
    "n_games",
    "seed",
    "full_season",
    "random_dates",
    "n_dates",
    "team",
    "month",
    "models",
    "model_version",
    "compare",
    "include_postseason",
    "output_dir",
    "verbose",
    "skip_odds",
    "skip_weather",
]:
    check(
        f"REQ-BT-056: --{flag.replace('_', '-')}",
        hasattr(args, flag),
        f"missing arg: {flag}",
    )

# REQ-BT-057: --quick preset
quick_args = parse_args(["--quick"])
check("REQ-BT-057a: --quick sets n_games=20", quick_args.n_games == 20)
check("REQ-BT-057b: --quick sets skip_odds", quick_args.skip_odds is True)
check("REQ-BT-057c: --quick sets skip_weather", quick_args.skip_weather is True)

# REQ-BT-058: --full preset
full_args = parse_args(["--full"])
check("REQ-BT-058a: --full sets full_season", full_args.full_season is True)
check(
    "REQ-BT-058b: --full sets include_postseason", full_args.include_postseason is True
)

# REQ-BT-056 defaults
check("REQ-BT-056: default seed=42", args.seed == 42)
check("REQ-BT-056: default n_games=100", args.n_games == 100)

# ---------------------------------------------------------------------------
# §5.8 Data Quality (REQ-BT-059 through REQ-BT-061)
# ---------------------------------------------------------------------------
print("\n=== §5.8 DATA QUALITY ===")
cli_src = inspect.getsource(run_backtest)

# REQ-BT-059: data quality scoring
check(
    "REQ-BT-059: data quality tracking",
    "data_quality_score" in hdb_src or "quality_score" in hdb_src,
)
check("REQ-BT-059b: quality components", "data_quality" in cli_src)

# REQ-BT-060: quality filter with --min-quality
check("REQ-BT-060: min_quality filter", "min_quality" in cli_src)

# REQ-BT-061: temporal leakage audit
check(
    "REQ-BT-061: leakage audit",
    "leakage_audit" in cli_src.lower() or "TEMPORAL LEAKAGE" in cli_src,
)

# ---------------------------------------------------------------------------
# §5.9 Performance (REQ-BT-062 through REQ-BT-064)
# ---------------------------------------------------------------------------
print("\n=== §5.9 PERFORMANCE ===")
from app.services.etl.mlb.backtest.cache import (
    cached_api_call,
    clear_cache,
    get_cache_stats,
)

cache_src_file = os.path.join(base, "backtest", "cache.py")
with open(cache_src_file) as f:
    cache_src = f.read()

# REQ-BT-062: rate limiting
check("REQ-BT-062: rate limiting", "rate_limit" in cache_src or "sleep" in cache_src)

# REQ-BT-063: SQLite cache
check(
    "REQ-BT-063a: SQLite cache", "sqlite3" in cache_src or "sqlite" in cache_src.lower()
)
check("REQ-BT-063b: cached_api_call()", callable(cached_api_call))
check("REQ-BT-063c: get_cache_stats()", callable(get_cache_stats))

# REQ-BT-064: --clear-cache and --cache-only
check("REQ-BT-064a: clear_cache()", callable(clear_cache))
check("REQ-BT-064b: --cache-only support", hasattr(args, "cache_only"))
check("REQ-BT-064c: --clear-cache support", hasattr(args, "clear_cache"))

# ---------------------------------------------------------------------------
# Functional: test report generation with mock data
# ---------------------------------------------------------------------------
print("\n=== FUNCTIONAL: Report Generation ===")
mock_config = {
    "model_version": "test",
    "start_date": "2024-06-01",
    "end_date": "2024-09-01",
    "n_games": 50,
    "seed": 42,
}
mock_metrics = {
    "game_metrics": {
        "brier_score": 0.22,
        "ml_accuracy": 0.565,
        "ml_correct": 28,
        "n_games": 50,
        "ou_accuracy": 0.54,
        "ou_total": 40,
        "total_mae": 2.3,
        "run_line_accuracy": 0.525,
        "rl_correct": 26,
        "calibration": [
            {
                "bucket": "0.45-0.55",
                "predicted": 0.50,
                "actual": 0.49,
                "count": 20,
                "status": "OK",
            },
            {
                "bucket": "0.55-0.65",
                "predicted": 0.59,
                "actual": 0.61,
                "count": 15,
                "status": "OK",
            },
        ],
    },
    "k_metrics": {
        "n_pitchers": 30,
        "k_mae": 1.4,
        "k_gold_standard_rate": 0.23,
        "k_gold_standard_count": 7,
        "by_k9_tier": {"low_k9": "1.8", "mid_k9": "1.3", "high_k9": "1.1"},
    },
    "hit_metrics": {
        "n_predictions": 100,
        "hit_mae": 0.8,
        "hit_accuracy": 0.35,
        "hit_correct": 35,
    },
    "hr_metrics": {
        "n_predictions": 200,
        "hr_top10_hit_rate": 0.195,
        "hr_top10_hits": 39,
        "hr_top10_total": 200,
        "hr_auc_roc": 0.641,
    },
    "market_metrics": {
        "n_games_with_odds": 35,
        "market_brier": 0.21,
        "model_vs_market_brier": 0.01,
        "simulated_roi": -0.03,
        "simulated_bets": 15,
    },
    "segmented": {
        "by_month": {
            "Jun": {"ml_accuracy": 0.55},
            "Jul": {"ml_accuracy": 0.58},
            "Aug": {"ml_accuracy": 0.56},
        },
        "by_temperature": {
            "<60F": {"ml_accuracy": 0.53},
            "60-80F": {"ml_accuracy": 0.57},
            ">80F": {"ml_accuracy": 0.55},
        },
    },
}
mock_dq = {
    "avg_quality": 0.78,
    "real_weather": 12,
    "with_odds": 35,
    "with_pitcher": 48,
}

report = generate_summary_report(mock_config, mock_metrics, mock_dq)
check("Report: non-empty", len(report) > 200)
check("Report: contains YETIBETS", "YETIBETS" in report)
check("Report: contains Brier Score", "Brier Score" in report)
check("Report: contains ML Accuracy", "Moneyline Accuracy" in report)
check("Report: contains K section", "STRIKEOUT" in report)
check("Report: contains HR section", "HOME RUN" in report)
check("Report: contains calibration", "CALIBRATION" in report)
check("Report: contains data quality", "DATA QUALITY" in report)
check("Report: contains segmented", "SEGMENTED" in report or "By Month" in report)

# Comparison report
comp = generate_comparison_report(mock_config, mock_metrics, mock_metrics, "v1", "v2")
check("Comparison: non-empty", len(comp) > 100)
check("Comparison: contains header", "MODEL COMPARISON" in comp)
check("Comparison: contains metrics", "Brier Score" in comp)

# ---------------------------------------------------------------------------
# Functional: BacktestScorer with mock data
# ---------------------------------------------------------------------------
print("\n=== FUNCTIONAL: Scorer Computation ===")
scorer = BacktestScorer()

# Add some mock game results
for i in range(20):
    wp = 0.45 + (i % 10) * 0.02
    actual_home_win = 1 if i % 3 != 0 else 0
    total_pred = 8.5
    actual_total = 7 + (i % 5)

    prediction = {
        "predicted_home_wp": wp,
        "predicted_total": total_pred,
        "predicted_run_line": 0.5 if wp > 0.5 else -0.5,
        "model_confidence": abs(wp - 0.5) * 2,
        "model_type": "heuristic",
        "pre_calibration_wp": wp,
        "calibration_applied": False,
    }
    actuals = {
        "home_score": 5 if actual_home_win else 3,
        "away_score": 3 if actual_home_win else 5,
        "actual_total": actual_total,
        "actual_winner": "home" if actual_home_win else "away",
        "run_margin": 2,
    }
    metadata = {
        "game_date": f"2024-07-{(i+1):02d}",
        "venue_name": "Test Park",
        "temperature": 72 + i,
        "data_quality_score": 0.75,
        "had_historical_odds": i % 2 == 0,
        "market_implied_prob": 0.50 + (i % 5) * 0.02 if i % 2 == 0 else None,
        "market_total": 8.5 if i % 2 == 0 else None,
    }
    scorer.add_game_result(prediction, actuals, metadata)

# K results
for i in range(10):
    scorer.add_k_result(
        "home",
        5.5 + i * 0.2,
        5 + (i % 3),
        projected_ip=5.5,
        actual_ip=5.0 + i * 0.2,
        pitcher_k9=8.5,
        n_starts=10,
    )

# Hit results
for i in range(10):
    scorer.add_hit_result("home", 4.5, 4 + (i % 3))

# HR results
for i in range(10):
    scorer.add_hr_result(0.3 + i * 0.05, 1 if i < 3 else 0, f"2024-07-{(i+1):02d}")

metrics = scorer.compute_all_metrics()
gm = metrics["game_metrics"]
km = metrics["k_metrics"]
hm = metrics["hit_metrics"]
hrm = metrics["hr_metrics"]

check("Scorer: brier_score computed", gm.get("brier_score") is not None)
check("Scorer: ml_accuracy computed", gm.get("ml_accuracy") is not None)
check("Scorer: ou_accuracy computed", gm.get("ou_accuracy") is not None)
check("Scorer: total_mae computed", gm.get("total_mae") is not None)
check("Scorer: run_line_accuracy computed", gm.get("run_line_accuracy") is not None)
check("Scorer: k_mae computed", km.get("k_mae") is not None)
check(
    "Scorer: k_gold_standard_rate computed", km.get("k_gold_standard_rate") is not None
)
check("Scorer: hit_mae computed", hm.get("hit_mae") is not None)
check("Scorer: hr_auc_roc computed", hrm.get("hr_auc_roc") is not None)
check("Scorer: hr_top10_hit_rate computed", hrm.get("hr_top10_hit_rate") is not None)
check("Scorer: calibration table", len(gm.get("calibration", [])) > 0)

# Segmented analysis
seg = metrics.get("segmented", {})
check("Scorer: segmented by_month", "by_month" in seg)

# Market metrics
mm = metrics.get("market_metrics", {})
check("Scorer: market metrics computed", mm.get("n_games_with_odds", 0) > 0)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\n{'='*70}")
print(f" RESULTS: {passed} passed, {failed} failed, {warnings} warnings")
print(f"{'='*70}")

if failed > 0:
    print(f"\n {failed} requirement(s) not met!")
    sys.exit(1)
else:
    print(f"\n All {passed} checks PASSED!")
    sys.exit(0)
