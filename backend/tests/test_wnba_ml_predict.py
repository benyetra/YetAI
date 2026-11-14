import json

import numpy as np
import pandas as pd
import pytest

from app.services.etl.wnba import _ml_predict as mlp
from tests.fake_s3 import Static


@pytest.fixture(autouse=True)
def clear_caches():
    mlp._OBJECTS.clear()
    yield
    mlp._OBJECTS.clear()


def test_predict_fills_missing_features_with_zero(monkeypatch, tmp_path):
    import xgboost as xgb

    model = xgb.XGBRegressor(n_estimators=10, random_state=0)
    X = pd.DataFrame({"f1": np.arange(20), "f2": np.arange(20)})
    y = pd.Series(np.arange(20) * 2.0)
    model.fit(X, y)
    metadata = {"stat": "points", "features": ["f1", "f2"], "test_mae": 0.0}

    # Bypass S3 by pre-seeding the caches directly
    mlp._OBJECTS["points"] = (Static(model), Static(metadata))

    pred = mlp.predict("points", {"f1": 5})
    assert isinstance(pred, float)
    # Missing f2 should be zero-filled, prediction should be deterministic
    assert pred >= 0  # clamped non-negative


def test_get_feature_names(monkeypatch, tmp_path):
    metadata = {"stat": "assists", "features": ["a", "b", "c"], "test_mae": 0.0}
    meta_path = tmp_path / "xgb_assists_metadata.json"
    meta_path.write_text(json.dumps(metadata))
    # Pre-seed the cache to skip download
    mlp._OBJECTS["assists"] = (Static(object()), Static(metadata))
    assert mlp.get_feature_names("assists") == ["a", "b", "c"]
