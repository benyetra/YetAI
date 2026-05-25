"""Summarize NHL backtest metrics and compare against committed CI baselines."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.services.etl.nhl.backtest.scorer import NHLBacktestScorer

# Higher MAE and lower O/U hit rate are worse (NHL-specific vs MLB).
DEFAULT_NHL_BACKTEST_TOLERANCES: dict[str, float] = {
    "goalie_mae": 0.5,
    "sog_mae": 0.3,
    "totals_mae": 0.25,
    "ou_hit_rate": 0.03,
}


@dataclass(frozen=True)
class BaselineCheckResult:
    """Outcome of comparing summarized metrics to a baseline file."""

    passed: bool
    failures: list[str] = field(default_factory=list)


def summarize_nhl_backtest_metrics(
    scorer_or_dict: NHLBacktestScorer | Mapping[str, Any],
) -> dict[str, Any]:
    """Flatten nested ``compute_all_metrics()`` output for regression gates."""
    if isinstance(scorer_or_dict, NHLBacktestScorer):
        raw = scorer_or_dict.compute_all_metrics()
    else:
        raw = dict(scorer_or_dict)

    goalie = raw.get("goalie_metrics") or {}
    sog = raw.get("sog_metrics") or {}
    totals = raw.get("totals_metrics") or {}
    agg = raw.get("aggregate_ou") or {}

    summary: dict[str, Any] = {}
    if goalie.get("n_goalie"):
        summary["n_goalie"] = int(goalie["n_goalie"])
    if goalie.get("goalie_mae") is not None:
        summary["goalie_mae"] = float(goalie["goalie_mae"])
    if sog.get("n_sog"):
        summary["n_sog"] = int(sog["n_sog"])
    if sog.get("sog_mae") is not None:
        summary["sog_mae"] = float(sog["sog_mae"])
    if totals.get("n_totals"):
        summary["n_totals"] = int(totals["n_totals"])
    if totals.get("totals_mae") is not None:
        summary["totals_mae"] = float(totals["totals_mae"])
    if agg.get("ou_hit_rate") is not None:
        summary["ou_hit_rate"] = float(agg["ou_hit_rate"])
        summary["ou_n"] = int(agg.get("ou_n", 0))

    return summary


def _load_baseline_metrics(baseline_path: str | Path) -> dict[str, Any]:
    path = Path(baseline_path)
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if "metrics" in payload and isinstance(payload["metrics"], dict):
        return dict(payload["metrics"])
    return {
        k: v
        for k, v in payload.items()
        if not k.startswith("_") and k not in ("description", "updated_at", "preset")
    }


def check_metrics_against_baseline(
    metrics: Mapping[str, Any],
    baseline_path: str | Path,
    tolerances: Mapping[str, float] | None = None,
) -> BaselineCheckResult:
    """Fail when summarized metrics regress beyond tolerance vs baseline."""
    tol = {**DEFAULT_NHL_BACKTEST_TOLERANCES, **(tolerances or {})}
    baseline = _load_baseline_metrics(baseline_path)
    failures: list[str] = []

    for mae_key, tol_key in (
        ("goalie_mae", "goalie_mae"),
        ("sog_mae", "sog_mae"),
        ("totals_mae", "totals_mae"),
    ):
        if (
            mae_key in baseline
            and mae_key in metrics
            and metrics.get(mae_key) is not None
        ):
            limit = float(baseline[mae_key]) + float(tol[tol_key])
            current = float(metrics[mae_key])
            if current > limit:
                failures.append(
                    f"{mae_key} {current:.2f} > baseline {baseline[mae_key]:.2f} "
                    f"+ tolerance {tol[tol_key]:.2f} (max {limit:.2f})"
                )

    if (
        "ou_hit_rate" in baseline
        and baseline.get("ou_hit_rate") is not None
        and "ou_hit_rate" in metrics
        and metrics.get("ou_hit_rate") is not None
    ):
        ou_tol = float(tol["ou_hit_rate"])
        limit = float(baseline["ou_hit_rate"]) - ou_tol
        current = float(metrics["ou_hit_rate"])
        if current < limit:
            failures.append(
                f"ou_hit_rate {current:.4f} < baseline {baseline['ou_hit_rate']:.4f} "
                f"- tolerance {ou_tol:.4f} (min {limit:.4f})"
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
