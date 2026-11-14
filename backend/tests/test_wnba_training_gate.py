"""WNBA/NBA trainers: chronological split, holdout-only validation, champion-gated upload (L2/L10)."""

from __future__ import annotations

import json
import pickle
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services.etl.nba.ml_training import train_totals_model as nba_totals
from app.services.etl.wnba.ml_training import (
    run_train_props,
    train_spread_model,
    train_totals_model as wnba_totals,
    validate_model,
)
from app.services.ml import model_store
from tests.fake_s3 import FakeS3

WINDOW = dict(season_start=date(2025, 5, 1), season_end=date(2025, 9, 30))


class Const:
    """Live model that always predicts ``v``."""

    def __init__(self, v):
        self.v = v

    def predict(self, X):
        return np.full(len(X), float(self.v))


class Linear:
    """Live model predicting ``k * X[col]`` (a near-perfect oracle for the toy data)."""

    def __init__(self, col, k):
        self.col, self.k = col, k

    def predict(self, X):
        return self.k * X[self.col].to_numpy()


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(model_store.boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(
        "app.services.ml.upload_to_s3.boto3.client", lambda *_a, **_k: fake
    )
    return fake


def _live(s3, prefix, name, model, features, **meta):
    s3.put(f"{prefix}/{name}.pkl", pickle.dumps(model), "e1")
    s3.put(
        f"{prefix}/{name}_metadata.json",
        json.dumps({"features": features, **meta}).encode(),
        "e1",
    )


def _props(n=200):
    rng = np.random.default_rng(0)
    x = rng.normal(15, 5, n)
    feats = pd.DataFrame({"points_l5": x, "minutes_l5": rng.normal(28, 4, n)})
    return feats, pd.Series(0.7 * x + rng.normal(0, 3, n), name="points")


# ---- L10: props split + validation -------------------------------------------------


def test_props_split_is_chronological_and_validation_is_holdout_only(monkeypatch):
    feats, target = _props()
    monkeypatch.setattr(
        run_train_props.build_training_dataset, "build", lambda *a: (feats, target)
    )
    seen = {}
    real = validate_model.validate

    def spy(stat, model, X, y):
        seen["n"] = len(X)
        seen["first"] = X.index[0]
        return real(stat, model, X, y)

    monkeypatch.setattr(run_train_props.validate_model, "validate", spy)
    out = run_train_props.run("points", **WINDOW)
    assert out["metadata"]["split"] == "chronological"
    assert seen["n"] == 40 and seen["first"] == 160  # last 20%, not all 200 rows
    assert out["validation"]["n_validation_rows"] == 40


# ---- L2: props gate ----------------------------------------------------------------


def test_props_rejected_by_champion_does_not_touch_s3(s3, monkeypatch):
    feats, target = _props()
    monkeypatch.setattr(
        run_train_props.build_training_dataset, "build", lambda *a: (feats, target)
    )
    # A live model that predicts the truth better than any candidate can.
    _live(
        s3,
        "wnba/ml_models",
        "xgb_points",
        Linear("points_l5", 0.7),
        ["points_l5", "minutes_l5"],
    )
    out = run_train_props.run("points", upload=True, **WINDOW)
    assert out["status"] == "rejected_by_champion"
    assert "s3_keys" not in out
    assert s3.names("put") == [] and s3.names("copy") == []


def test_props_better_candidate_uploads_with_manifest_and_archive(s3, monkeypatch):
    feats, target = _props()
    monkeypatch.setattr(
        run_train_props.build_training_dataset, "build", lambda *a: (feats, target)
    )
    _live(s3, "wnba/ml_models", "xgb_points", Const(500), ["points_l5"])  # terrible
    out = run_train_props.run("points", upload=True, **WINDOW)
    assert out["status"] == "ok"
    assert out["s3_keys"]["manifest_key"] == "wnba/ml_models/xgb_points_manifest.json"
    assert out["gate"]["archive_stamp"]
    assert "wnba/ml_models/xgb_points_manifest.json" in s3.objects


# ---- L2: spread --------------------------------------------------------------------


def test_spread_chronological_and_rejected_by_champion(s3, monkeypatch):
    rng = np.random.default_rng(1)
    n = 100
    x = rng.normal(0, 5, n)
    feats = pd.DataFrame({"elo_diff": x, "pace_adj": rng.normal(0, 1, n)})
    target = pd.Series(x + rng.normal(0, 2, n), name="margin")
    monkeypatch.setattr(train_spread_model, "build", lambda *a: (feats, target))

    _live(
        s3,
        "wnba/ml_models",
        "xgb_spread",
        Linear("elo_diff", 1.0),
        ["elo_diff", "pace_adj"],
    )
    out = train_spread_model.run(upload=True, skip_gate=True, **WINDOW)
    assert out["metadata"]["split"] == "chronological"
    assert out["status"] == "rejected_by_champion"
    assert s3.names("put") == []


# ---- L2 (item 5): totals -----------------------------------------------------------


def _totals(feature_names, n=120):
    rng = np.random.default_rng(2)
    feats = pd.DataFrame(
        rng.normal(0, 1, (n, len(feature_names))), columns=feature_names
    )
    feats["heuristic_total"] = rng.normal(160, 5, n)
    target = pd.Series(
        1.5 * feats[feature_names[1]] + rng.normal(0, 0.05, n), name="residual"
    )
    dates = pd.Series([date(2025, 5, 1) + timedelta(days=i // 2) for i in range(n)])
    return feats, target, dates


def test_wnba_totals_rejected_by_champion_and_ungated_path_gone(s3, monkeypatch):
    names = wnba_totals.feature_names()
    feats, target, dates = _totals(names)
    monkeypatch.setattr(wnba_totals, "build", lambda *a: (feats, target, dates, {}))
    second = names[1]

    _live(s3, "wnba/ml_models", "gbm_totals_residual", Linear(second, 1.5), names)
    out = wnba_totals.run(upload=True, skip_gate=True, **WINDOW)
    assert out["status"] == "rejected_by_champion"
    assert s3.names("put") == [] and s3.names("copy") == []


def test_wnba_totals_first_upload_writes_manifest(s3, monkeypatch):
    names = wnba_totals.feature_names()
    feats, target, dates = _totals(names)
    monkeypatch.setattr(wnba_totals, "build", lambda *a: (feats, target, dates, {}))
    out = wnba_totals.run(upload=True, skip_gate=True, **WINDOW)
    assert out["status"] == "ok" and out["gate"]["status"] == "first_upload"
    assert "wnba/ml_models/gbm_totals_residual_manifest.json" in s3.objects
    assert "wnba/ml_models/gbm_totals_residual_metadata.json" in s3.objects


def test_nba_totals_rejected_by_champion(s3, monkeypatch):
    names = nba_totals.feature_names()
    feats, target, _ = _totals(names)
    monkeypatch.setattr(nba_totals, "build", lambda *a: (feats, target))
    second = names[1]

    _live(s3, "nba/ml_models", "gbm_totals_residual", Linear(second, 1.5), names)
    out = nba_totals.run(upload=True, **WINDOW)
    assert out["status"] == "rejected_by_champion"
    assert s3.names("put") == [] and s3.names("copy") == []
