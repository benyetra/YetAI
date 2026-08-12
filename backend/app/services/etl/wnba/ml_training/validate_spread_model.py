"""Validate WNBA spread margin model against MAE/Brier gates before upload."""

from __future__ import annotations

from typing import Any

from app.services.etl.wnba.ml_training.config import (
    SPREAD_BRIER_GATE,
    SPREAD_MAE_GATE,
)


def validate_holdout(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Check holdout margin MAE and win-prob Brier against upload gates.

    Expects ``test_mae`` / ``test_brier`` (or ``holdout.margin_mae`` /
    ``holdout.brier``) from ``train_spread_model``.
    """
    holdout = metadata.get("holdout") or {}
    mae = holdout.get("margin_mae", metadata.get("test_mae"))
    brier = holdout.get("brier", metadata.get("test_brier"))

    if mae is None or brier is None:
        return {
            "passes_gate": False,
            "gate_threshold_mae": SPREAD_MAE_GATE,
            "gate_threshold_brier": SPREAD_BRIER_GATE,
            "mae": float(mae) if mae is not None else None,
            "brier": float(brier) if brier is not None else None,
            "reason": "missing_holdout_metrics",
        }

    mae_f = float(mae)
    brier_f = float(brier)
    if mae_f > SPREAD_MAE_GATE:
        return {
            "passes_gate": False,
            "gate_threshold_mae": SPREAD_MAE_GATE,
            "gate_threshold_brier": SPREAD_BRIER_GATE,
            "mae": mae_f,
            "brier": brier_f,
            "reason": "holdout_mae_above_gate",
        }
    if brier_f > SPREAD_BRIER_GATE:
        return {
            "passes_gate": False,
            "gate_threshold_mae": SPREAD_MAE_GATE,
            "gate_threshold_brier": SPREAD_BRIER_GATE,
            "mae": mae_f,
            "brier": brier_f,
            "reason": "holdout_brier_above_gate",
        }
    return {
        "passes_gate": True,
        "gate_threshold_mae": SPREAD_MAE_GATE,
        "gate_threshold_brier": SPREAD_BRIER_GATE,
        "mae": mae_f,
        "brier": brier_f,
        "reason": None,
    }
