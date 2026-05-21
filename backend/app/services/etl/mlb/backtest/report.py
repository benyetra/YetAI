"""Report Generation for Backtesting.

Generates text summary reports and CSV output files matching the format
of /mlb/results and /mlb/game_results dashboards.

REQ-BT-054: Text summary to stdout + CSV output.
REQ-BT-055: --compare side-by-side report.
"""

import csv
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "..",
    "..",
    "..",
    "scripts",
    "mlb_backtest_results",
)
RUNS_DIR = os.path.join(OUTPUT_DIR, "runs")


def generate_summary_report(config, metrics, data_quality_summary):
    """Generate the text summary report printed to stdout (REQ-BT-054).

    Returns:
        str: formatted report text
    """
    game = metrics.get("game_metrics", {})
    k = metrics.get("k_metrics", {})
    hit = metrics.get("hit_metrics", {})
    hr = metrics.get("hr_metrics", {})
    market = metrics.get("market_metrics", {})
    segmented = metrics.get("segmented", {})

    lines = []
    w = 80

    lines.append("=" * w)
    lines.append(" YETAI MLB BACKTEST REPORT")
    lines.append(
        f' Model Version: {config.get("model_version", "current")}    '
        f'Run: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
    )
    lines.append(
        f' Period: {config.get("start_date", "?")} -> {config.get("end_date", "?")}    '
        f'Games: {game.get("n_games", 0)}    '
        f'Seed: {config.get("seed", "none")}'
    )
    lines.append("=" * w)
    lines.append("")

    # Game-level accuracy
    lines.append(" GAME-LEVEL ACCURACY")
    lines.append(" " + "-" * (w - 2))

    brier = game.get("brier_score")
    market_brier = market.get("market_brier")
    brier_str = f"{brier:.4f}" if brier is not None else "N/A"
    if market_brier is not None:
        delta = market.get("model_vs_market_brier", 0)
        brier_str += f"        (Market: {market_brier:.4f}, Delta: {delta:+.4f})"

    lines.append(f" Brier Score:              {brier_str}")

    ml_acc = game.get("ml_accuracy")
    ml_correct = game.get("ml_correct", 0)
    n = game.get("n_games", 0)
    lines.append(f" Moneyline Accuracy:       {ml_acc:.1%}         ({ml_correct}/{n})")

    ou_acc = game.get("ou_accuracy")
    ou_total = game.get("ou_total", 0)
    if ou_acc is not None:
        ou_correct = int(ou_acc * ou_total)
        lines.append(
            f" O/U Accuracy:             {ou_acc:.1%}         ({ou_correct}/{ou_total} with total comparisons)"
        )
    else:
        lines.append(f" O/U Accuracy:             N/A")

    total_mae = game.get("total_mae")
    lines.append(
        f" Run Total MAE:            {total_mae:.2f} runs"
        if total_mae
        else " Run Total MAE:            N/A"
    )

    rl_acc = game.get("run_line_accuracy")
    rl_correct = game.get("rl_correct", 0)
    lines.append(f" Run Line Accuracy:        {rl_acc:.1%}         ({rl_correct}/{n})")

    lines.append("")

    # Calibration
    calibration = game.get("calibration", [])
    if calibration:
        lines.append(" CALIBRATION")
        lines.append(" " + "-" * (w - 2))
        lines.append(
            f' {"Bucket":<16} {"Predicted":<12} {"Actual":<10} {"Count":<10} {"Status":<10}'
        )
        for c in calibration:
            status_icon = "OK" if c["status"] == "OK" else "!! WARNING"
            lines.append(
                f' {c["bucket"]:<16} {c["predicted"]:<12.3f} {c["actual"]:<10.3f} '
                f'{c["count"]:<10} {status_icon}'
            )
        lines.append("")

    # K projections
    if k:
        n_pitchers = k.get("n_pitchers", 0)
        lines.append(f" STRIKEOUT PROJECTIONS ({n_pitchers} pitchers backtested)")
        lines.append(" " + "-" * (w - 2))
        lines.append(f' K Projection MAE:         {k.get("k_mae", 0):.2f} strikeouts')
        gold_rate = k.get("k_gold_standard_rate", 0)
        gold_count = k.get("k_gold_standard_count", 0)
        lines.append(
            f" Gold Standard (+/-0.25):   {gold_rate:.1%}         ({gold_count}/{n_pitchers})"
        )

        by_k9 = k.get("by_k9_tier", {})
        if by_k9:
            lines.append(
                f" By K/9 Tier:              "
                f'Low(<7): {by_k9.get("low_k9", "N/A")} | '
                f'Mid(7-9): {by_k9.get("mid_k9", "N/A")} | '
                f'High(>9): {by_k9.get("high_k9", "N/A")}'
            )
        lines.append("")

    # Hit predictions
    if hit:
        lines.append(f' HIT PREDICTIONS ({hit.get("n_predictions", 0)} predictions)')
        lines.append(" " + "-" * (w - 2))
        lines.append(f' Hit MAE:                  {hit.get("hit_mae", 0):.2f} hits')
        lines.append(
            f' Hit Accuracy (rounded):   {hit.get("hit_accuracy", 0):.1%}         '
            f'({hit.get("hit_correct", 0)}/{hit.get("n_predictions", 0)})'
        )
        lines.append("")

    # HR predictions
    if hr:
        lines.append(
            f' HOME RUN PREDICTIONS ({hr.get("n_predictions", 0)} predictions)'
        )
        lines.append(" " + "-" * (w - 2))
        lines.append(
            f' Top-10 Hit Rate:          {hr.get("hr_top10_hit_rate", 0):.1%}         '
            f'({hr.get("hr_top10_hits", 0)}/{hr.get("hr_top10_total", 0)})'
        )
        lines.append(f' AUC-ROC:                  {hr.get("hr_auc_roc", 0):.3f}')
        lines.append("")

    # Market comparison
    if market and market.get("n_games_with_odds", 0) > 0:
        lines.append(
            f' MARKET COMPARISON ({market["n_games_with_odds"]} games with odds)'
        )
        lines.append(" " + "-" * (w - 2))
        delta = market.get("model_vs_market_brier", 0)
        verdict = "Model Better" if delta < 0 else "Market Better"
        lines.append(f" Model vs Market Brier:    {delta:+.4f}  ({verdict})")
        lines.append(
            f' Simulated ROI (edge>3%):  {market.get("simulated_roi", 0):+.1%}  '
            f'({market.get("simulated_bets", 0)} bets)'
        )
        lines.append("")

    # Segmented analysis
    by_month = segmented.get("by_month", {})
    if by_month:
        lines.append(" SEGMENTED ANALYSIS")
        lines.append(" " + "-" * (w - 2))
        month_strs = [f'{m}: {d["ml_accuracy"]:.1%} ML' for m, d in by_month.items()]
        lines.append(f' By Month:     {" | ".join(month_strs)}')

        by_temp = segmented.get("by_temperature", {})
        if by_temp:
            temp_strs = [f'{t}: {d["ml_accuracy"]:.1%}' for t, d in by_temp.items()]
            lines.append(f' By Temp:      {" | ".join(temp_strs)}')

        lines.append("")

    # Data quality
    lines.append(" DATA QUALITY")
    lines.append(" " + "-" * (w - 2))
    lines.append(
        f' Avg Quality Score:        {data_quality_summary.get("avg_quality", 0):.2f}'
    )
    lines.append(
        f" Games with real weather:  "
        f'{data_quality_summary.get("real_weather", 0)}/{n} '
        f'({data_quality_summary.get("real_weather", 0)/max(n,1):.1%})'
    )
    lines.append(
        f" Games with market odds:   "
        f'{data_quality_summary.get("with_odds", 0)}/{n} '
        f'({data_quality_summary.get("with_odds", 0)/max(n,1):.1%})'
    )
    lines.append(
        f" Games with pitcher data:  "
        f'{data_quality_summary.get("with_pitcher", 0)}/{n} '
        f'({data_quality_summary.get("with_pitcher", 0)/max(n,1):.1%})'
    )
    lines.append("")
    lines.append("=" * w)

    return "\n".join(lines)


def generate_comparison_report(config, metrics_a, metrics_b, label_a, label_b):
    """Generate side-by-side comparison report (REQ-BT-055).

    Args:
        config: shared config dict
        metrics_a: first backtest metrics
        metrics_b: second backtest metrics
        label_a: label for first run
        label_b: label for second run

    Returns:
        str: formatted comparison report
    """
    w = 80
    lines = []

    lines.append("=" * w)
    lines.append(f" MODEL COMPARISON: {label_a} vs {label_b}")
    lines.append(
        f' Period: {config.get("start_date", "?")} -> {config.get("end_date", "?")}    '
        f'Games: {config.get("n_games", "?")}    Seed: {config.get("seed", "?")}'
    )
    lines.append("=" * w)
    lines.append("")

    ga = metrics_a.get("game_metrics", {})
    gb = metrics_b.get("game_metrics", {})
    ka = metrics_a.get("k_metrics", {})
    kb = metrics_b.get("k_metrics", {})
    hra = metrics_a.get("hr_metrics", {})
    hrb = metrics_b.get("hr_metrics", {})

    header = (
        f' {"Metric":<28} {label_a:<14} {label_b:<14} {"Delta":<10} {"Verdict":<10}'
    )
    lines.append(header)
    lines.append(" " + "-" * (w - 2))

    def _row(name, val_a, val_b, fmt=".4f", lower_better=True):
        if val_a is None or val_b is None:
            return f' {name:<28} {"N/A":<14} {"N/A":<14}'
        sa = f"{val_a:{fmt}}"
        sb = f"{val_b:{fmt}}"
        delta = val_b - val_a
        sd = f"{delta:+{fmt}}"
        if lower_better:
            verdict = "Better" if delta < 0 else ("Worse" if delta > 0 else "Same")
        else:
            verdict = "Better" if delta > 0 else ("Worse" if delta < 0 else "Same")
        return f" {name:<28} {sa:<14} {sb:<14} {sd:<10} {verdict}"

    lines.append(_row("Brier Score", ga.get("brier_score"), gb.get("brier_score")))
    lines.append(
        _row(
            "ML Accuracy",
            ga.get("ml_accuracy"),
            gb.get("ml_accuracy"),
            ".1%",
            lower_better=False,
        )
    )
    lines.append(
        _row(
            "O/U Accuracy",
            ga.get("ou_accuracy"),
            gb.get("ou_accuracy"),
            ".1%",
            lower_better=False,
        )
    )
    lines.append(_row("Total MAE", ga.get("total_mae"), gb.get("total_mae"), ".2f"))
    lines.append(_row("K MAE", ka.get("k_mae"), kb.get("k_mae"), ".2f"))
    lines.append(
        _row(
            "K Gold Standard",
            ka.get("k_gold_standard_rate"),
            kb.get("k_gold_standard_rate"),
            ".1%",
            lower_better=False,
        )
    )
    lines.append(
        _row(
            "HR Top-10 Hit Rate",
            hra.get("hr_top10_hit_rate"),
            hrb.get("hr_top10_hit_rate"),
            ".1%",
            lower_better=False,
        )
    )

    lines.append("=" * w)

    return "\n".join(lines)


def write_csv_report(backtest_id, game_results, output_dir=None):
    """Write per-game results to CSV (REQ-BT-054).

    Returns:
        str: path to the CSV file
    """
    if output_dir is None:
        output_dir = os.path.abspath(OUTPUT_DIR)

    os.makedirs(output_dir, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"backtest_{backtest_id[:8]}_{date_str}.csv"
    filepath = os.path.join(output_dir, filename)

    fieldnames = [
        "game_date",
        "home_team",
        "away_team",
        "venue_name",
        "predicted_home_wp",
        "predicted_total",
        "predicted_run_line",
        "model_confidence",
        "model_type",
        "home_score",
        "away_score",
        "actual_total",
        "actual_winner",
        "ml_correct",
        "total_error",
        "run_line_correct",
        "brier_contribution",
        "data_quality_score",
        "pre_calibration_wp",
        "calibration_applied",
        "temperature",
        "used_estimated_weather",
        "had_historical_odds",
    ]

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in game_results:
            writer.writerow(r)

    logger.info(f"Wrote CSV report to {filepath}")
    return filepath
