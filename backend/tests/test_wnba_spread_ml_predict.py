from unittest.mock import patch

from app.services.etl.wnba import _spread_ml_predict as smp
from app.services.etl.wnba.ml_training.config import SPREAD_MAE_GATE
from tests.fake_s3 import Static


def _seed(monkeypatch, model, metadata):
    monkeypatch.setattr(smp, "_OBJECTS", (Static(model), Static(metadata)))


def _passing_metadata(**extra):
    meta = {
        "features": ["elo_diff", "pace_adj"],
        "test_mae": 5.0,
        "test_brier": 0.2,
        "validation": {"passes_gate": True},
    }
    meta.update(extra)
    return meta


def test_predict_margin_when_model_loaded(monkeypatch):
    class FakeModel:
        def predict(self, vec):
            return [3.5]

    _seed(monkeypatch, FakeModel(), _passing_metadata())

    margin = smp.predict_margin({"elo_diff": 10.0, "pace_adj": 0.5})
    assert margin == 3.5


def test_predict_margin_none_when_not_loaded(monkeypatch):
    _seed(monkeypatch, None, None)
    assert smp.predict_margin({"elo_diff": 1.0}) is None


def test_model_available_false_when_quality_gate_fails(monkeypatch):
    _seed(
        monkeypatch,
        object(),
        {
            "features": ["elo_diff"],
            "test_mae": SPREAD_MAE_GATE + 3.0,
            "test_brier": 0.1,
            "validation": {"passes_gate": False},
        },
    )
    monkeypatch.delenv("WNBA_SPREAD_ML_FORCE", raising=False)
    assert smp.model_available() is False


def test_model_available_true_when_force_override(monkeypatch):
    _seed(
        monkeypatch,
        object(),
        {
            "features": ["elo_diff"],
            "validation": {"passes_gate": False},
        },
    )
    monkeypatch.setenv("WNBA_SPREAD_ML_FORCE", "1")
    assert smp.model_available() is True


def test_legacy_metadata_mae_only_gate(monkeypatch):
    monkeypatch.delenv("WNBA_SPREAD_ML_FORCE", raising=False)
    assert smp.passes_quality_gate({"test_mae": SPREAD_MAE_GATE - 0.1}) is True
    assert smp.passes_quality_gate({"test_mae": SPREAD_MAE_GATE + 0.1}) is False
