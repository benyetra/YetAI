"""NBA _ml_predict metadata helpers (no S3)."""

from __future__ import annotations

from app.services.etl.nba import _ml_predict as mlp
from tests.fake_s3 import Static


def _install(model, meta):
    mlp._OBJECTS["points"] = (Static(model), Static(meta))


def test_feature_names_fallback_to_features(monkeypatch):
    monkeypatch.setattr(mlp, "_OBJECTS", {})
    _install(
        object(),
        {"features": ["a", "b"], "test_mae": 4.2, "model_version": "xgb-test"},
    )
    assert mlp.get_feature_names("points") == ["a", "b"]
    assert mlp.get_holdout_mae("points") == 4.2
    assert mlp.get_model_version("points") == "xgb-test"
