"""Validate WNBA totals residual model against upload gate (beat heuristic)."""

from __future__ import annotations

from typing import Any

# Soft ceiling kept for logging/telemetry only — not the upload gate.
# Absolute residual MAE ≤ 1.0 was a stretch target; promote uses live shadow.
from app.services.etl.wnba.ml_training.config import TOTALS_RESIDUAL_MAE_GATE

GATE_NAME = "ml_beats_heuristic_full_total_mae"


def validate_holdout(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Upload gate: holdout full-total MAE must beat the heuristic baseline.

    Expects ``metadata["holdout"]`` from ``train_totals_model`` with
    ``ml_full_total_mae``, ``heuristic_full_total_mae``, and ideally
    ``ml_beats_heuristic``. Residual MAE is reported but not gating.
    """
    holdout = metadata.get("holdout") or {}
    residual_mae = holdout.get("residual_mae")
    ml_mae = holdout.get("ml_full_total_mae")
    heuristic_mae = holdout.get("heuristic_full_total_mae")

    if ml_mae is None or heuristic_mae is None:
        beats = holdout.get("ml_beats_heuristic")
        if beats is None:
            return {
                "passes_gate": False,
                "gate": GATE_NAME,
                "gate_threshold": TOTALS_RESIDUAL_MAE_GATE,
                "mae": float(residual_mae) if residual_mae is not None else None,
                "ml_full_total_mae": None,
                "heuristic_full_total_mae": None,
                "holdout": holdout,
                "reason": "missing_holdout_full_total_mae",
            }
        passes = bool(beats)
    else:
        ml_f = float(ml_mae)
        h_f = float(heuristic_mae)
        passes = ml_f < h_f

    reason = None if passes else "ml_full_total_mae_not_better_than_heuristic"
    return {
        "passes_gate": passes,
        "gate": GATE_NAME,
        "gate_threshold": TOTALS_RESIDUAL_MAE_GATE,
        "mae": float(residual_mae) if residual_mae is not None else None,
        "ml_full_total_mae": float(ml_mae) if ml_mae is not None else None,
        "heuristic_full_total_mae": (
            float(heuristic_mae) if heuristic_mae is not None else None
        ),
        "holdout": holdout,
        "reason": reason,
    }
