from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.services.etl.wnba.ml_training import train_model, validate_model, upload_to_s3


@pytest.fixture
def small_dataset():
    rng = np.random.default_rng(0)
    n = 200
    feats = pd.DataFrame(
        {
            "points_l3": rng.normal(15, 5, n),
            "points_l5": rng.normal(15, 5, n),
            "points_l10": rng.normal(15, 5, n),
            "minutes_l5": rng.normal(28, 4, n),
            "season_points_avg": rng.normal(15, 5, n),
            "season_minutes_avg": rng.normal(28, 4, n),
            "season_usage_pct": rng.normal(20, 3, n),
            "season_ts_pct": rng.normal(0.55, 0.05, n),
            "opp_points_allowed_per_game": rng.normal(80, 4, n),
            "opp_defensive_rating": rng.normal(100, 5, n),
            "opp_pace": rng.normal(80, 3, n),
            "rest_days": rng.integers(1, 5, n),
            "is_back_to_back": rng.integers(0, 2, n),
            "pace_factor": rng.normal(1.0, 0.05, n),
        }
    )
    # Target: ~70% noise + 30% signal from points_l5
    target = pd.Series(
        0.7 * feats["points_l5"] + 0.3 * rng.normal(0, 3, n), name="points"
    )
    return feats, target


def test_train_returns_model_and_metadata(small_dataset):
    feats, target = small_dataset
    model, meta = train_model.train("points", feats, target)
    assert meta["stat"] == "points"
    assert meta["test_mae"] > 0
    assert "features" in meta
    assert set(meta["features"]) == set(feats.columns)


def test_validate_computes_gate_pass_or_fail(small_dataset):
    feats, target = small_dataset
    model, _ = train_model.train("points", feats, target)
    result = validate_model.validate("points", model, feats, target)
    # On training data we expect a low MAE (likely passes the 4.5 gate).
    assert result["mae"] < 4.5
    assert result["passes_gate"] is True


def test_validate_fails_gate_for_unrealistic_threshold(small_dataset):
    feats, target = small_dataset
    model, _ = train_model.train("points", feats, target)
    # Force a tighter gate
    with patch.dict(validate_model.MAE_GATE, {"points": 0.1}):
        result = validate_model.validate("points", model, feats, target)
        assert result["passes_gate"] is False


def test_upload_calls_s3_put(monkeypatch, small_dataset):
    calls = []

    class FakeS3:
        def upload_file(self, local_path, bucket, key):
            calls.append((bucket, key))

    monkeypatch.setattr(
        "app.services.etl.wnba.ml_training.upload_to_s3.boto3",
        type("M", (), {"client": staticmethod(lambda _: FakeS3())}),
    )
    feats, target = small_dataset
    model, meta = train_model.train("points", feats, target)
    result = upload_to_s3.upload("points", model, meta)
    assert result["model_key"] == "wnba/ml_models/xgb_points.pkl"
    assert result["metadata_key"] == "wnba/ml_models/xgb_points_metadata.json"
    assert len(calls) == 2
