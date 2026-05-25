"""Offline tests for NBA prop ML training (no DB, no S3)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.services.etl.nba.ml_training import (
    run_train_props,
    train_model,
    upload_to_s3,
    validate_model,
)
from app.services.etl.nba.ml_training.config import NBA_ML_CONFIG


@pytest.fixture
def small_dataset():
    rng = np.random.default_rng(2)
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
            "opp_points_allowed_per_game": rng.normal(110, 4, n),
            "opp_defensive_rating": rng.normal(110, 5, n),
            "opp_pace": rng.normal(100, 3, n),
            "rest_days": rng.integers(1, 5, n),
            "is_back_to_back": rng.integers(0, 2, n),
            "pace_factor": rng.normal(1.0, 0.05, n),
        }
    )
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
    assert result["gate_threshold"] == NBA_ML_CONFIG.mae_gate["points"]
    assert result["mae"] < 5.0
    assert result["passes_gate"] is True


def test_validate_fails_gate_for_unrealistic_threshold(small_dataset):
    feats, target = small_dataset
    model, _ = train_model.train("points", feats, target)
    with patch.dict(validate_model.MAE_GATE, {"points": 0.1}):
        result = validate_model.validate("points", model, feats, target)
        assert result["passes_gate"] is False


def test_upload_calls_s3_put(monkeypatch, small_dataset):
    calls = []

    class FakeS3:
        def upload_file(self, local_path, bucket, key):
            calls.append((bucket, key))

    monkeypatch.setattr(
        "app.services.etl.nba.ml_training.upload_to_s3.boto3",
        type("M", (), {"client": staticmethod(lambda _: FakeS3())}),
    )
    feats, target = small_dataset
    model, meta = train_model.train("points", feats, target)
    meta = run_train_props._enrich_metadata("points", meta)
    result = upload_to_s3.upload("points", model, meta)
    assert result["model_key"] == "nba/ml_models/xgb_points.pkl"
    assert result["metadata_key"] == "nba/ml_models/xgb_points_metadata.json"
    assert len(calls) == 2


def test_enrich_metadata_shape(small_dataset):
    _, meta = train_model.train("points", *small_dataset)
    enriched = run_train_props._enrich_metadata("points", meta)
    assert enriched["feature_names"] == enriched["features"]
    assert enriched["holdout_mae"] == enriched["test_mae"]
    assert enriched["model_version"]
    assert len(enriched["model_version"]) <= 20


def test_run_pipeline_mocked_build_and_upload(small_dataset, monkeypatch):
    feats, target = small_dataset

    monkeypatch.setattr(
        "app.services.etl.nba.ml_training.run_train_props.build_training_dataset.build",
        lambda stat, start, end: (feats, target),
    )
    upload_calls = []
    monkeypatch.setattr(
        "app.services.etl.nba.ml_training.run_train_props.upload_to_s3.upload",
        lambda stat, model, meta: upload_calls.append(stat) or {"model_key": "k"},
    )

    out = run_train_props.run(
        "points",
        season_start=date(2024, 10, 1),
        season_end=date(2025, 4, 30),
        upload=True,
    )
    assert out["status"] == "ok"
    assert out["validation"]["passes_gate"] is True
    assert "model_version" in out["metadata"]
    assert upload_calls == ["points"]


def test_run_gate_failed_skips_upload(small_dataset, monkeypatch):
    feats, target = small_dataset
    monkeypatch.setattr(
        "app.services.etl.nba.ml_training.run_train_props.build_training_dataset.build",
        lambda stat, start, end: (feats, target),
    )
    upload_calls = []
    monkeypatch.setattr(
        "app.services.etl.nba.ml_training.run_train_props.upload_to_s3.upload",
        lambda *a, **k: upload_calls.append(1),
    )
    with patch.dict(validate_model.MAE_GATE, {"points": 0.01}):
        out = run_train_props.run(
            "points",
            season_start=date(2024, 10, 1),
            season_end=date(2025, 4, 30),
            upload=True,
        )
    assert out["status"] == "gate_failed"
    assert upload_calls == []


def test_run_dry_run_skips_train(monkeypatch):
    monkeypatch.setattr(
        "app.services.etl.nba.ml_training.run_train_props.build_training_dataset.build",
        lambda stat, start, end: (pd.DataFrame({"a": [1, 2, 3]}), pd.Series([1, 2, 3])),
    )
    out = run_train_props.run(
        "points",
        season_start=date(2024, 10, 1),
        season_end=date(2025, 4, 30),
        dry_run=True,
    )
    assert out["status"] == "dry_run"
    assert out["rows"] == 3


def test_run_insufficient_data():
    with patch(
        "app.services.etl.nba.ml_training.run_train_props.build_training_dataset.build",
        lambda stat, start, end: (pd.DataFrame(), pd.Series(dtype=float)),
    ):
        out = run_train_props.run(
            "points",
            season_start=date(2024, 10, 1),
            season_end=date(2025, 4, 30),
        )
    assert out["status"] == "insufficient_data"
