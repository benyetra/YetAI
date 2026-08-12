"""WNBA spread ML upload / quality gate."""

from __future__ import annotations

from app.services.etl.wnba.ml_training.config import (
    SPREAD_BRIER_GATE,
    SPREAD_MAE_GATE,
)
from app.services.etl.wnba.ml_training.validate_spread_model import validate_holdout


def test_validate_passes_when_mae_and_brier_under_gates():
    metadata = {
        "test_mae": SPREAD_MAE_GATE - 0.5,
        "test_brier": SPREAD_BRIER_GATE - 0.01,
    }
    result = validate_holdout(metadata)
    assert result["passes_gate"] is True
    assert result["mae"] == metadata["test_mae"]
    assert result["brier"] == metadata["test_brier"]


def test_validate_fails_when_mae_above_gate():
    metadata = {
        "test_mae": SPREAD_MAE_GATE + 2.0,
        "test_brier": 0.1,
    }
    result = validate_holdout(metadata)
    assert result["passes_gate"] is False
    assert result["reason"] == "holdout_mae_above_gate"


def test_validate_fails_when_brier_above_gate():
    metadata = {
        "test_mae": 5.0,
        "test_brier": SPREAD_BRIER_GATE + 0.05,
    }
    result = validate_holdout(metadata)
    assert result["passes_gate"] is False
    assert result["reason"] == "holdout_brier_above_gate"


def test_validate_fails_when_metrics_missing():
    result = validate_holdout({})
    assert result["passes_gate"] is False
    assert result["reason"] == "missing_holdout_metrics"
