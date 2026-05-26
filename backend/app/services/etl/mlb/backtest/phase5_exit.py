"""Phase 5 exit check: MC total MAE baseline vs lineup-weighted profiles."""

from __future__ import annotations

from statistics import mean
from typing import Any


def compute_phase5_exit_metrics(game_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize dual-MC backtest rows (baseline vs lineup profile MC)."""
    rows = [
        r
        for r in game_results
        if r.get("mc_baseline_total_error") is not None
        and r.get("mc_lineup_total_error") is not None
    ]
    if not rows:
        return {
            "n_games": 0,
            "lineup_weighted_pct": 0.0,
            "baseline_total_mae": None,
            "lineup_total_mae": None,
            "mae_delta": None,
        }

    baseline_errors = [abs(float(r["mc_baseline_total_error"])) for r in rows]
    lineup_errors = [abs(float(r["mc_lineup_total_error"])) for r in rows]
    weighted = sum(1 for r in rows if r.get("mc_lineup_weighted"))
    baseline_mae = mean(baseline_errors)
    lineup_mae = mean(lineup_errors)

    return {
        "n_games": len(rows),
        "lineup_weighted_pct": round(100.0 * weighted / len(rows), 1),
        "lineup_weighted_games": weighted,
        "baseline_total_mae": round(baseline_mae, 3),
        "lineup_total_mae": round(lineup_mae, 3),
        "mae_delta": round(lineup_mae - baseline_mae, 3),
    }


def evaluate_phase5_exit(
    metrics: dict[str, Any],
    *,
    max_mae_regression: float = 0.05,
    min_lineup_weighted_pct: float = 50.0,
) -> dict[str, Any]:
    """Roadmap exit: total MAE not worse than baseline; profiles applied on most games."""
    reasons: list[str] = []
    if metrics.get("n_games", 0) == 0:
        return {
            "pass": False,
            "reasons": [
                "no dual-MC game rows (enable --phase5-exit-check with game model)"
            ],
        }

    mae_delta = metrics.get("mae_delta")
    if mae_delta is None:
        reasons.append("missing MAE delta")
    elif mae_delta > max_mae_regression:
        reasons.append(
            f"lineup MC total MAE worse by {mae_delta:+.3f} runs "
            f"(limit +{max_mae_regression:.3f})"
        )

    lw_pct = float(metrics.get("lineup_weighted_pct") or 0.0)
    if lw_pct < min_lineup_weighted_pct:
        reasons.append(
            f"lineup_weighted on {lw_pct:.1f}% of games "
            f"(need >={min_lineup_weighted_pct:.0f}% — rebuild profiles for holdout dates "
            "and ensure local DATABASE_PUBLIC_URL is set)"
        )

    return {"pass": not reasons, "reasons": reasons}


def format_phase5_exit_report(
    metrics: dict[str, Any], evaluation: dict[str, Any]
) -> str:
    """Human-readable Phase 5 holdout summary."""
    w = 72
    lines = [
        "=" * w,
        " PHASE 5 EXIT CHECK — MC lineup profiles vs baseline MC",
        "=" * w,
        f" Games compared:           {metrics.get('n_games', 0)}",
        f" Lineup-weighted games:    {metrics.get('lineup_weighted_games', 0)} "
        f"({metrics.get('lineup_weighted_pct', 0)}%)",
        f" Baseline MC total MAE:    {metrics.get('baseline_total_mae', 'N/A')}",
        f" Lineup MC total MAE:      {metrics.get('lineup_total_mae', 'N/A')}",
        f" Delta (lineup - base):    {metrics.get('mae_delta', 'N/A')} runs",
        "",
    ]
    if evaluation.get("pass"):
        lines.append(" VERDICT: PASS — lineup-weighted MC is not worse on total MAE")
    else:
        lines.append(" VERDICT: FAIL")
        for reason in evaluation.get("reasons") or []:
            lines.append(f"  - {reason}")
    lines.append("=" * w)
    return "\n".join(lines)
