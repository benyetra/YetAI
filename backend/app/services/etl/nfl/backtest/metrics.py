"""Summarize NFL backtest metrics and compare against CI baselines."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.services.etl.nfl.backtest.scorer import NFLBacktestScorer

DEFAULT_NFL_BACKTEST_TOLERANCES: dict[str, float] = {
    "qb_mae": 8.0,
    "kicker_mae": 0.35,
    "ou_hit_rate": 0.03,
}


@dataclass(frozen=True)
class BaselineCheckResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def summarize_nfl_backtest_metrics(
    scorer_or_dict: NFLBacktestScorer | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(scorer_or_dict, NFLBacktestScorer):
        raw = scorer_or_dict.compute_all_metrics()
    else:
        raw = dict(scorer_or_dict)

    qb = raw.get("qb_metrics") or {}
    kicker = raw.get("kicker_metrics") or {}
    agg = raw.get("aggregate_ou") or {}

    summary: dict[str, Any] = {}
    if qb.get("n_qb"):
        summary["n_qb"] = int(qb["n_qb"])
    if qb.get("qb_mae") is not None:
        summary["qb_mae"] = float(qb["qb_mae"])
    if qb.get("qb_ou_hit_rate") is not None:
        summary["qb_ou_hit_rate"] = float(qb["qb_ou_hit_rate"])
        summary["qb_ou_n"] = int(qb.get("qb_ou_n", 0))
    if kicker.get("n_kicker"):
        summary["n_kicker"] = int(kicker["n_kicker"])
    if kicker.get("kicker_mae") is not None:
        summary["kicker_mae"] = float(kicker["kicker_mae"])
    if kicker.get("kicker_ou_hit_rate") is not None:
        summary["kicker_ou_hit_rate"] = float(kicker["kicker_ou_hit_rate"])
        summary["kicker_ou_n"] = int(kicker.get("kicker_ou_n", 0))
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
    tol = {**DEFAULT_NFL_BACKTEST_TOLERANCES, **(tolerances or {})}
    baseline = _load_baseline_metrics(baseline_path)
    failures: list[str] = []

    for mae_key, tol_key in (("qb_mae", "qb_mae"), ("kicker_mae", "kicker_mae")):
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
    result = check_metrics_against_baseline(metrics, baseline_path, tolerances)
    if not result.passed:
        raise AssertionError("; ".join(result.failures))
