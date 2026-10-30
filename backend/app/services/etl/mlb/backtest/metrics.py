"""Summarize backtest metrics and compare against committed CI baselines."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.services.etl.mlb.backtest.scorer import BacktestScorer

# Higher Brier / hit MAE and lower ML accuracy are worse.
DEFAULT_BACKTEST_TOLERANCES: dict[str, float] = {
    "mean_brier": 0.02,
    "moneyline_accuracy": 0.03,
    "hit_mae": 0.5,
}


@dataclass(frozen=True)
class BaselineCheckResult:
    """Outcome of comparing summarized metrics to a baseline file."""

    passed: bool
    failures: list[str] = field(default_factory=list)


def summarize_backtest_metrics(
    scorer_or_dict: BacktestScorer | Mapping[str, Any]
) -> dict[str, Any]:
    """Flatten nested ``compute_all_metrics()`` output for regression gates.

    Accepts a :class:`BacktestScorer` (calls ``compute_all_metrics()``) or the
    nested dict returned by that method / persisted in run JSON.

    Keys (when data is present): ``mean_brier``, ``moneyline_accuracy``,
    ``hit_mae`` (optional), ``n_games``.
    """
    if isinstance(scorer_or_dict, BacktestScorer):
        raw = scorer_or_dict.compute_all_metrics()
    else:
        raw = dict(scorer_or_dict)

    game = raw.get("game_metrics") or {}
    hit = raw.get("hit_metrics") or {}

    summary: dict[str, Any] = {
        "n_games": game.get("n_games", 0),
    }
    if game.get("brier_score") is not None:
        summary["mean_brier"] = float(game["brier_score"])
    if game.get("ml_accuracy") is not None:
        summary["moneyline_accuracy"] = float(game["ml_accuracy"])
    if hit.get("hit_mae") is not None:
        summary["hit_mae"] = float(hit["hit_mae"])

    return summary


def _load_baseline_metrics(baseline_path: str | Path) -> dict[str, Any]:
    path = Path(baseline_path)
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if "metrics" in payload and isinstance(payload["metrics"], dict):
        return dict(payload["metrics"])
    return {
        k: v for k, v in payload.items() if not k.startswith("_") and k != "description"
    }


def check_metrics_against_baseline(
    metrics: Mapping[str, Any],
    baseline_path: str | Path,
    tolerances: Mapping[str, float] | None = None,
) -> BaselineCheckResult:
    """Fail when summarized metrics regress beyond tolerance vs baseline.

    - ``mean_brier``: fails if current > baseline + tolerance (default +0.02).
    - ``moneyline_accuracy``: fails if current < baseline - tolerance (default -0.03).
    - ``hit_mae``: checked only when both current and baseline include it;
      fails if current > baseline + tolerance (default +0.5).
    """
    tol = {**DEFAULT_BACKTEST_TOLERANCES, **(tolerances or {})}
    baseline = _load_baseline_metrics(baseline_path)
    failures: list[str] = []

    if "mean_brier" in baseline and "mean_brier" in metrics:
        limit = float(baseline["mean_brier"]) + float(tol["mean_brier"])
        current = float(metrics["mean_brier"])
        if current > limit:
            failures.append(
                f"mean_brier {current:.5f} > baseline {baseline['mean_brier']:.5f} "
                f"+ tolerance {tol['mean_brier']:.5f} (max {limit:.5f})"
            )

    if "moneyline_accuracy" in baseline and "moneyline_accuracy" in metrics:
        limit = float(baseline["moneyline_accuracy"]) - float(tol["moneyline_accuracy"])
        current = float(metrics["moneyline_accuracy"])
        if current < limit:
            failures.append(
                f"moneyline_accuracy {current:.4f} < baseline "
                f"{baseline['moneyline_accuracy']:.4f} - tolerance "
                f"{tol['moneyline_accuracy']:.4f} (min {limit:.4f})"
            )

    if (
        "hit_mae" in baseline
        and baseline.get("hit_mae") is not None
        and "hit_mae" in metrics
        and metrics.get("hit_mae") is not None
    ):
        hit_tol = float(tol.get("hit_mae", DEFAULT_BACKTEST_TOLERANCES["hit_mae"]))
        limit = float(baseline["hit_mae"]) + hit_tol
        current = float(metrics["hit_mae"])
        if current > limit:
            failures.append(
                f"hit_mae {current:.2f} > baseline {baseline['hit_mae']:.2f} "
                f"+ tolerance {hit_tol:.2f} (max {limit:.2f})"
            )

    return BaselineCheckResult(passed=not failures, failures=failures)


def assert_metrics_against_baseline(
    metrics: Mapping[str, Any],
    baseline_path: str | Path,
    tolerances: Mapping[str, float] | None = None,
) -> None:
    """Raise ``AssertionError`` when :func:`check_metrics_against_baseline` fails."""
    result = check_metrics_against_baseline(metrics, baseline_path, tolerances)
    if not result.passed:
        raise AssertionError("; ".join(result.failures))
