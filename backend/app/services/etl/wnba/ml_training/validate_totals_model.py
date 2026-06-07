"""Validate WNBA totals residual model against MAE gate before upload."""

from __future__ import annotations

from typing import Any

from app.services.etl.wnba.ml_training.config import TOTALS_RESIDUAL_MAE_GATE


def validate_holdout(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Check holdout residual MAE from training metadata against the upload gate.

    Expects ``metadata["holdout"]["residual_mae"]`` from ``train_totals_model``.
    """
    holdout = metadata.get("holdout") or {}
    mae = holdout.get("residual_mae")
    if mae is None:
        return {
            "passes_gate": False,
            "gate_threshold": TOTALS_RESIDUAL_MAE_GATE,
            "mae": None,
            "reason": "missing_holdout_residual_mae",
        }

    mae_f = float(mae)
    passes = mae_f <= TOTALS_RESIDUAL_MAE_GATE
    return {
        "passes_gate": passes,
        "gate_threshold": TOTALS_RESIDUAL_MAE_GATE,
        "mae": mae_f,
        "holdout": holdout,
        "reason": None if passes else "holdout_mae_above_gate",
    }
