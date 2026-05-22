from unittest.mock import patch

from app.services.etl.wnba import _spread_ml_predict as smp


def test_predict_margin_when_model_loaded(monkeypatch):
    monkeypatch.setattr(smp, "_MODEL", object())
    monkeypatch.setattr(
        smp,
        "_METADATA",
        {"features": ["elo_diff", "pace_adj"]},
    )
    monkeypatch.setattr(smp, "_LOAD_FAILED", False)

    class FakeModel:
        def predict(self, vec):
            return [3.5]

    monkeypatch.setattr(smp, "_MODEL", FakeModel())

    margin = smp.predict_margin({"elo_diff": 10.0, "pace_adj": 0.5})
    assert margin == 3.5


def test_predict_margin_none_when_not_loaded(monkeypatch):
    monkeypatch.setattr(smp, "_MODEL", None)
    monkeypatch.setattr(smp, "_METADATA", None)
    monkeypatch.setattr(smp, "_LOAD_FAILED", True)
    assert smp.predict_margin({"elo_diff": 1.0}) is None
