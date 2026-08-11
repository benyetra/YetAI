"""Walk-forward kicker ML blend weight and kick-distance imputation (NFL-4.4)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

_DEFAULT_DISTANCE = 40.0
_NFL_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "nfl"
_WEIGHT_GRID = tuple(round(w, 2) for w in np.arange(0.0, 0.55, 0.05))


def _load_field_goal_history() -> pd.DataFrame | None:
    path = _NFL_DATA_DIR / "field_goal_data.csv"
    if not path.is_file():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def impute_kick_distance(
    kicker_data: Mapping[str, Any],
    team_data: Mapping[str, Any] | None = None,
    *,
    game_context: Mapping[str, Any] | None = None,
) -> float:
    """
    Estimate typical attempt distance from kicker/team history, not a flat 38.0.

    Priority: explicit game_context → kicker avg → nflverse CSV by kicker name →
    league mean from CSV → default 40.0.
    """
    ctx = game_context or {}
    if ctx.get("kick_distance") is not None:
        try:
            return float(ctx["kick_distance"])
        except (TypeError, ValueError):
            pass

    for key in ("avg_distance", "avg_kick_distance", "mean_kick_distance"):
        if kicker_data.get(key) is not None:
            try:
                return float(kicker_data[key])
            except (TypeError, ValueError):
                pass

    name = (
        kicker_data.get("name")
        or kicker_data.get("kicker_name")
        or kicker_data.get("kicker_player_name")
    )
    history = _load_field_goal_history()
    if history is not None and name and "kicker_player_name" in history.columns:
        subset = history[history["kicker_player_name"] == name]
        if subset.empty and "kicker" in history.columns:
            subset = history[history["kicker"] == name]
        if not subset.empty and "kick_distance" in subset.columns:
            return float(subset["kick_distance"].mean())

    if history is not None and "kick_distance" in history.columns:
        return float(history["kick_distance"].mean())

    _ = team_data
    return _DEFAULT_DISTANCE


def walk_forward_blend_weight(
    records: Sequence[Mapping[str, Any]],
    *,
    weight_grid: Sequence[float] | None = None,
    min_train: int = 5,
) -> float:
    """
    Walk-forward grid search minimizing MAE on projected FG made.

    Each record: ``statistical_fgs``, ``ml_fgs``, ``actual_fg_made``.
    """
    grid = list(weight_grid) if weight_grid is not None else list(_WEIGHT_GRID)
    if not grid:
        return float(os.getenv("NFL_KICKER_ML_BLEND_WEIGHT", "0.35"))

    rows = [
        r
        for r in records
        if r.get("statistical_fgs") is not None
        and r.get("ml_fgs") is not None
        and r.get("actual_fg_made") is not None
    ]
    if len(rows) < min_train + 1:
        return float(grid[min(len(grid) - 1, 7)])  # ~0.35 when default grid

    errors: dict[float, list[float]] = {w: [] for w in grid}
    for i in range(min_train, len(rows)):
        train = rows[:i]
        holdout = rows[i]
        actual = float(holdout["actual_fg_made"])
        stat = float(holdout["statistical_fgs"])
        ml = float(holdout["ml_fgs"])
        for w in grid:
            pred = (1.0 - w) * stat + w * ml
            errors[w].append(abs(pred - actual))

    best_w = min(grid, key=lambda w: float(np.mean(errors[w])) if errors[w] else 1e9)
    return float(best_w)


def resolve_blend_weight(
    tune_records: Sequence[Mapping[str, Any]] | None = None,
) -> float:
    """Env override → walk-forward on records → tuned JSON → 0.30."""
    tuned = os.getenv("NFL_KICKER_BLEND_TUNED_WEIGHT", "").strip()
    if tuned:
        try:
            return float(tuned)
        except ValueError:
            pass
    if tune_records:
        return walk_forward_blend_weight(tune_records)
    env_default = os.getenv("NFL_KICKER_ML_BLEND_WEIGHT", "").strip()
    if env_default:
        try:
            return float(env_default)
        except ValueError:
            pass
    # Shipped offline tune artifact (scripts/nfl_tune_kicker_blend.py --write)
    tune_path = (
        Path(__file__).resolve().parents[4]
        / "models"
        / "nfl"
        / "kicker_blend_tune.json"
    )
    if tune_path.is_file():
        try:
            payload = json.loads(tune_path.read_text())
            w = payload.get("NFL_KICKER_BLEND_TUNED_WEIGHT")
            if w is not None:
                return float(w)
        except Exception:
            pass
    return 0.30
