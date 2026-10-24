"""Fast model experiments on a cached prop dataset (chronological holdout).

Compares the shipped XGBoost against regularized variants, a model of the
residual over a player's recent average, and blends with that average. Every
number is MAE on the same latest-20% holdout; "usable" rows are those where the
5/10/20-game averages exist, which is where the naive baseline is defined.

    python -m app.services.etl.nba.ml_training.experiments \
        --stat points --start 2024-10-01 --end 2026-10-23
"""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb

from app.services.etl.nba.ml_training import build_training_dataset
from app.services.etl.nba.ml_training.config import NBA_ML_CONFIG
from app.services.ml import dataset_cache
from app.services.ml.train_model import DEFAULT_HYPERPARAMS, split

NAIVE_WINDOWS = (5, 10, 20)

CONFIGS: dict[str, dict[str, Any]] = {
    "default": {},
    "depth3": {"max_depth": 3, "n_estimators": 200, "learning_rate": 0.03},
    "depth2": {
        "max_depth": 2,
        "n_estimators": 300,
        "learning_rate": 0.03,
        "min_child_weight": 50,
    },
    "regularized": {
        "max_depth": 4,
        "n_estimators": 150,
        "learning_rate": 0.03,
        "subsample": 0.7,
        "colsample_bytree": 0.7,
        "reg_lambda": 5.0,
        "min_child_weight": 30,
    },
}


def _fit(params: dict, X: pd.DataFrame, y) -> xgb.XGBRegressor:
    model = xgb.XGBRegressor(**{**DEFAULT_HYPERPARAMS, **params})
    model.fit(X, y, verbose=False)
    return model


def run_experiments(
    stat_col: str, features_df: pd.DataFrame, target: pd.Series, base_window: int = 10
) -> list[dict[str, Any]]:
    """Rows of {name, mae_all, mae_usable, bias_usable} sorted by usable MAE."""
    X_tr, X_te, y_tr, y_te = split(features_df, target, chronological=True)
    cols = [f"{stat_col}_avg_{w}" for w in NAIVE_WINDOWS]
    base_col = f"{stat_col}_avg_{base_window}"
    usable = (X_te[cols] > 0).all(axis=1).to_numpy()
    y = np.asarray(y_te, dtype=float)

    def row(name: str, pred) -> dict[str, Any]:
        pred = np.asarray(pred, dtype=float)
        err = pred - y
        return {
            "name": name,
            "mae_all": float(np.mean(np.abs(err))),
            "mae_usable": float(np.mean(np.abs(err[usable]))),
            "bias_usable": float(np.mean(err[usable])),  # pred - actual
        }

    out = [row(f"naive avg_{w}", X_te[f"{stat_col}_avg_{w}"]) for w in NAIVE_WINDOWS]
    base_tr = np.asarray(X_tr[base_col], dtype=float)
    base_te = np.asarray(X_te[base_col], dtype=float)
    for name, params in CONFIGS.items():
        direct = _fit(params, X_tr, y_tr).predict(X_te)
        out.append(row(f"xgb {name}", direct))
        resid = _fit(params, X_tr, np.asarray(y_tr, dtype=float) - base_tr)
        over_base = base_te + resid.predict(X_te)
        out.append(row(f"xgb {name} on avg_{base_window} residual", over_base))
        out.append(
            row(
                f"blend 50/50 xgb {name} + avg_{base_window}",
                0.5 * direct + 0.5 * base_te,
            )
        )
        out.append(
            row(
                f"blend 50/50 residual {name} + avg_{base_window}",
                0.5 * over_base + 0.5 * base_te,
            )
        )
    return sorted(out, key=lambda r: r["mae_usable"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stat", required=True, choices=NBA_ML_CONFIG.supported_stats)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    key = dataset_cache.cache_key(NBA_ML_CONFIG.s3_prefix, args.stat, start, end)
    hit = dataset_cache.load(key)
    if hit is None:
        features_df, target = build_training_dataset.build(args.stat, start, end)
        dataset_cache.save(key, features_df, target)
    else:
        features_df, target = hit
    print(f"{args.stat}: {len(features_df)} rows ({start}..{end})")
    print(f"{'model':58s} {'MAE all':>8s} {'MAE usable':>11s} {'bias':>7s}")
    for r in run_experiments(args.stat, features_df, target):
        print(
            f"{r['name']:58s} {r['mae_all']:8.3f} {r['mae_usable']:11.3f} {r['bias_usable']:+7.2f}"
        )


if __name__ == "__main__":
    main()
