"""Train NBA spread margin XGBoost and optionally upload to S3.

The model replaces the Elo margin in spread_projector, so it is only uploaded
when it beats Elo on the same 20% holdout; the metadata records both MAEs and
_spread_ml_predict refuses any model whose metadata doesn't show the win.
The upload is also champion-gated: it must not be worse than the live model on
this holdout (status ``rejected_by_champion``). Rows with a market line also
report MAE against the line, and a model that loses to it there is not shipped.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import numpy as np

from app.services.etl.nba._spread_ml_predict import MIN_TRAINING_ROWS
from app.services.etl.nba.ml_training.build_spread_dataset import build
from app.services.etl.nba.ml_training.train_model import train
from app.services.ml.train_model import split
from app.services.etl.nba.ml_training import upload_to_s3

logger = logging.getLogger(__name__)

# Shallow and regularized: ~2.6k games of a noisy target overfit the prop
# defaults (train MAE 5.4 vs test 11.6).
SPREAD_HYPERPARAMS = {
    "n_estimators": 200,
    "max_depth": 2,
    "learning_rate": 0.03,
    "min_child_weight": 20,
}

# Margins the projector falls back to without a model.
BASELINE_COLUMNS = ("base_margin", "elo_pace_margin")

# Market line gate: only judged when the holdout has at least this many games
# with a line (the dataset builder leaves market_spread_home NaN otherwise).
MARKET_GATE_MIN_ROWS = 30


def _market_gate_enabled() -> bool:
    return os.getenv("NBA_SPREAD_MARKET_GATE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def market_holdout_mae(model, X_test, y_test) -> dict[str, float | int | None]:
    """Model vs market-line MAE on the holdout games that have a line.
    A home spread of -3.5 means the market projects the home team by +3.5."""
    lined = X_test["market_spread_home"].notna().to_numpy()
    n = int(lined.sum())
    if n == 0:
        return {
            "n_market_rows": 0,
            "market_test_mae": None,
            "model_mae_on_market_rows": None,
        }
    y = np.asarray(y_test, dtype=float)[lined]
    market = -np.asarray(X_test["market_spread_home"], dtype=float)[lined]
    pred = np.asarray(model.predict(X_test[lined]), dtype=float)
    return {
        "n_market_rows": n,
        "market_test_mae": float(np.mean(np.abs(market - y))),
        "model_mae_on_market_rows": float(np.mean(np.abs(pred - y))),
    }


def baseline_holdout_mae(features_df, target) -> float:
    """Best Elo-only MAE on the same 20% holdout ``train`` uses."""
    _, X_test, _, y_test = split(features_df, target, chronological=True)
    y = np.asarray(y_test, dtype=float)
    return min(
        float(np.mean(np.abs(np.asarray(X_test[c], dtype=float) - y)))
        for c in BASELINE_COLUMNS
    )


def run(
    *,
    season_start: date,
    season_end: date,
    upload: bool = False,
) -> dict:
    features_df, target = build(season_start, season_end)
    if len(features_df) < MIN_TRAINING_ROWS:
        return {
            "status": "insufficient_data",
            "rows": len(features_df),
            "min_required": MIN_TRAINING_ROWS,
        }

    model, metadata = train(
        "spread",
        features_df,
        target,
        hyperparams=SPREAD_HYPERPARAMS,
        chronological=True,
    )
    metadata = dict(metadata)
    metadata["baseline_test_mae"] = baseline_holdout_mae(features_df, target)
    metadata["beats_baseline"] = metadata["test_mae"] < metadata["baseline_test_mae"]
    result: dict[str, Any] = {
        "status": "ok",
        "metadata": metadata,
        "rows": len(features_df),
    }
    if not metadata["beats_baseline"]:
        logger.warning(
            "NBA spread model does not beat Elo: test_mae=%.3f baseline=%.3f",
            metadata["test_mae"],
            metadata["baseline_test_mae"],
        )
        result["status"] = "below_baseline"
        return result
    _, X_test, _, y_test = split(features_df, target, chronological=True)
    market = market_holdout_mae(model, X_test, y_test)
    metadata.update(market)
    metadata["data_window"] = f"{season_start}..{season_end}"
    logger.info("NBA spread holdout vs market line: %s", market)
    if (
        _market_gate_enabled()
        and market["n_market_rows"] >= MARKET_GATE_MIN_ROWS
        and market["model_mae_on_market_rows"] > market["market_test_mae"]
    ):
        logger.warning("NBA spread model does not beat the market line: %s", market)
        result["status"] = "below_baseline"
        result["reason"] = "does_not_beat_market_line"
        return result
    if upload:
        out = upload_to_s3.upload_gated(
            "spread",
            model,
            metadata,
            candidate_metric=metadata["test_mae"],
            metric_name="test_mae",
            score_champion=upload_to_s3.live_scorer(
                "spread", X_test, y_test, fill=float("nan")
            ),
        )
        result["gate"] = out
        if out["status"] == "rejected_by_champion":
            logger.warning(
                "NBA spread candidate rejected: holdout MAE %.3f vs live %.3f",
                out["candidate_metric"],
                out["champion_metric"],
            )
            result["status"] = "rejected_by_champion"
        else:
            result["s3_keys"] = {
                k: out[k] for k in ("model_key", "metadata_key", "manifest_key")
            }
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Train NBA spread ML model")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    out = run(
        season_start=date.fromisoformat(args.start),
        season_end=date.fromisoformat(args.end),
        upload=args.upload,
    )
    print(out)
    if out.get("status") != "ok":
        raise SystemExit(1)
