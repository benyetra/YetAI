"""Offline evaluation: meta-learner (Layer 3) vs calibrated game ensemble.

Unit-testable without DB. Production wiring should remain off until
``recommend_production_use`` is true on a temporal holdout (Brier lift >= 0.005).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.metrics import brier_score_loss

# Align with game_model DEFERRED_EVAL_BRIER_LIFT_MIN — meta must beat game ensemble by at least this.
META_BRIER_LIFT_MIN = 0.005


def _as_arrays(
    y_true: Sequence[float] | np.ndarray,
    p_game: Sequence[float] | np.ndarray,
    p_meta: Sequence[float] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y = np.asarray(y_true, dtype=float).ravel()
    p_g = np.clip(np.asarray(p_game, dtype=float).ravel(), 1e-6, 1 - 1e-6)
    p_m = np.clip(np.asarray(p_meta, dtype=float).ravel(), 1e-6, 1 - 1e-6)
    if not (len(y) == len(p_g) == len(p_m)):
        raise ValueError(
            f"y_true, p_game, p_meta must have same length; got {len(y)}, {len(p_g)}, {len(p_m)}"
        )
    if len(y) == 0:
        raise ValueError("need at least one row for evaluation")
    return y, p_g, p_m


def _ml_accuracy(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p >= 0.5).astype(int) == y.astype(int)))


def evaluate_meta_vs_baseline(
    y_true: Sequence[float] | np.ndarray,
    p_game: Sequence[float] | np.ndarray,
    p_meta: Sequence[float] | np.ndarray,
) -> dict[str, Any]:
    """Brier and moneyline accuracy for game ensemble vs meta-learner probabilities."""
    y, p_g, p_m = _as_arrays(y_true, p_game, p_meta)
    brier_game = float(brier_score_loss(y, p_g))
    brier_meta = float(brier_score_loss(y, p_m))
    acc_game = _ml_accuracy(y, p_g)
    acc_meta = _ml_accuracy(y, p_m)
    brier_lift = brier_game - brier_meta
    acc_lift = acc_meta - acc_game
    return {
        "n": int(len(y)),
        "brier_game": round(brier_game, 6),
        "brier_meta": round(brier_meta, 6),
        "brier_lift_game_minus_meta": round(brier_lift, 6),
        "ml_accuracy_game": round(acc_game, 6),
        "ml_accuracy_meta": round(acc_meta, 6),
        "ml_accuracy_lift_meta_minus_game": round(acc_lift, 6),
        "meta_beats_game_brier": brier_lift > 0,
        "meta_beats_game_brier_at_threshold": brier_lift >= META_BRIER_LIFT_MIN,
        "brier_lift_threshold": META_BRIER_LIFT_MIN,
    }


def recommend_production_use(
    eval_result: Mapping[str, Any],
    *,
    brier_lift_min: float = META_BRIER_LIFT_MIN,
) -> bool:
    """True when meta-learner Brier lift on holdout meets the promotion gate."""
    lift = eval_result.get("brier_lift_game_minus_meta")
    if lift is None:
        return False
    return float(lift) >= float(brier_lift_min)


def _rows_to_arrays(
    rows: Sequence[Mapping[str, Any]]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y_list: list[float] = []
    p_game_list: list[float] = []
    p_meta_list: list[float] = []
    for row in rows:
        y = row.get("y_true", row.get("home_win"))
        p_g = row.get("p_game", row.get("xgb_win_prob", row.get("home_win_prob")))
        p_m = row.get("p_meta", row.get("meta_prob", row.get("meta_home_win_prob")))
        if y is None or p_g is None or p_m is None:
            raise ValueError(
                "each row needs y_true/home_win, p_game/xgb_win_prob/home_win_prob, "
                "and p_meta/meta_prob/meta_home_win_prob"
            )
        y_list.append(float(y))
        p_game_list.append(float(p_g))
        p_meta_list.append(float(p_m))
    return _as_arrays(y_list, p_game_list, p_meta_list)


def compare_meta_learner_vs_game_ensemble(
    metrics_or_rows: Mapping[str, Any] | Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Compare stacked meta probabilities to calibrated game ensemble.

    Accepts either:
    - dict with ``y_true``, ``p_game``, ``p_meta`` array-like values, or
    - sequence of row dicts (see ``_rows_to_arrays`` key aliases).
    """
    if isinstance(metrics_or_rows, Mapping):
        if "y_true" in metrics_or_rows or "home_win" in metrics_or_rows:
            y_key = "y_true" if "y_true" in metrics_or_rows else "home_win"
            p_g_key = next(
                (
                    k
                    for k in ("p_game", "xgb_win_prob", "home_win_prob")
                    if k in metrics_or_rows
                ),
                None,
            )
            p_m_key = next(
                (
                    k
                    for k in ("p_meta", "meta_prob", "meta_home_win_prob")
                    if k in metrics_or_rows
                ),
                None,
            )
            if p_g_key is None or p_m_key is None:
                raise ValueError("metrics dict needs p_game and p_meta (or aliases)")
            result = evaluate_meta_vs_baseline(
                metrics_or_rows[y_key],
                metrics_or_rows[p_g_key],
                metrics_or_rows[p_m_key],
            )
        elif "rows" in metrics_or_rows:
            y, p_g, p_m = _rows_to_arrays(metrics_or_rows["rows"])
            result = evaluate_meta_vs_baseline(y, p_g, p_m)
        else:
            raise ValueError("unsupported metrics dict shape")
    else:
        y, p_g, p_m = _rows_to_arrays(metrics_or_rows)
        result = evaluate_meta_vs_baseline(y, p_g, p_m)

    result["recommend_production_use"] = recommend_production_use(result)
    result["recommendation"] = (
        "use_meta_learner"
        if result["recommend_production_use"]
        else "skip_meta_learner"
    )
    return result


def synthetic_offline_rows(scenario: str) -> list[dict[str, float]]:
    """Fixture rows for CLI ``--evaluate-offline`` (no DB)."""
    scenarios = {
        "meta_worse": [
            {"home_win": 1, "p_game": 0.62, "p_meta": 0.48},
            {"home_win": 0, "p_game": 0.38, "p_meta": 0.55},
            {"home_win": 1, "p_game": 0.58, "p_meta": 0.42},
            {"home_win": 0, "p_game": 0.41, "p_meta": 0.59},
        ],
        "meta_equal": [
            {"home_win": 1, "p_game": 0.70, "p_meta": 0.70},
            {"home_win": 0, "p_game": 0.30, "p_meta": 0.30},
            {"home_win": 1, "p_game": 0.65, "p_meta": 0.65},
            {"home_win": 0, "p_game": 0.35, "p_meta": 0.35},
        ],
        "meta_better": [
            {"home_win": 1, "p_game": 0.52, "p_meta": 0.88},
            {"home_win": 0, "p_game": 0.48, "p_meta": 0.12},
            {"home_win": 1, "p_game": 0.51, "p_meta": 0.90},
            {"home_win": 0, "p_game": 0.49, "p_meta": 0.10},
        ],
    }
    if scenario not in scenarios:
        raise ValueError(
            f"unknown scenario {scenario!r}; choose from {sorted(scenarios)}"
        )
    return scenarios[scenario]


def run_offline_fixture_comparison(scenario: str = "meta_better") -> dict[str, Any]:
    """Run compare on a built-in synthetic scenario (for CLI and smoke)."""
    rows = synthetic_offline_rows(scenario)
    return compare_meta_learner_vs_game_ensemble(rows)
