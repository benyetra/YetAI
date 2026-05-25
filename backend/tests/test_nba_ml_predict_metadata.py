"""NBA _ml_predict metadata helpers (no S3)."""

from __future__ import annotations

from app.services.etl.nba import _ml_predict as mlp


def _reset_caches():
    mlp._models.clear()
    mlp._metadatas.clear()


def test_feature_names_fallback_to_features():
    _reset_caches()
    mlp._models["points"] = object()
    mlp._metadatas["points"] = {
        "features": ["a", "b"],
        "test_mae": 4.2,
        "model_version": "xgb-test",
    }
    assert mlp.get_feature_names("points") == ["a", "b"]
    assert mlp.get_holdout_mae("points") == 4.2
    assert mlp.get_model_version("points") == "xgb-test"
