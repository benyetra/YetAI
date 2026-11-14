"""NBA loaders pick up a newly uploaded model and do not fail stickily (L1/L16)."""

from __future__ import annotations

import json
import pickle

import pytest

from app.services.etl.nba import _ml_predict as mlp
from app.services.etl.nba import _spread_ml_predict as smp
from app.services.etl.nba import totals_ml as tml
from app.services.ml import model_store as ms
from tests.fake_s3 import FakeS3


class Model:
    def __init__(self, tag):
        self.tag = tag

    def predict(self, X):
        return [1.0 if self.tag == "OLD" else 2.0]


def _put(s3, prefix, name, tag, etag, meta=None):
    s3.put(f"{prefix}/{name}.pkl", pickle.dumps(Model(tag)), etag)
    s3.put(
        f"{prefix}/{name}_metadata.json",
        json.dumps(meta or {"features": ["a"], "n_features": 1}).encode(),
        etag,
    )


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(ms.boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(ms, "REFRESH_SECONDS", 0)
    for mod, attrs in (
        (mlp, {"_OBJECTS": {}}),
        (smp, {"_OBJECTS": None, "_warned_for": None}),
        (tml, {"_OBJECTS": None}),
    ):
        for k, v in attrs.items():
            monkeypatch.setattr(mod, k, v, raising=False)
    return fake


def test_prop_model_cache_picks_up_new_upload(s3):
    _put(s3, "nba/ml_models", "xgb_points", "OLD", "e1")
    assert mlp.predict("points", {"a": 1}) == 1.0
    _put(s3, "nba/ml_models", "xgb_points", "NEW", "e2")
    assert mlp.predict("points", {"a": 1}) == 2.0  # same process, no restart


def test_prop_model_version_from_manifest_then_metadata(s3):
    _put(s3, "nba/ml_models", "xgb_points", "OLD", "e1", {"features": ["a"], "model_version": "meta-v"})
    assert mlp.get_model_version("points") == "meta-v"
    s3.put("nba/ml_models/xgb_points_manifest.json", json.dumps({"version": "xgb-202611"}).encode(), "e2")
    _put(s3, "nba/ml_models", "xgb_points", "NEW", "e3")
    assert mlp.get_model_version("points") == "xgb-202611"


def test_prop_model_s3_blip_keeps_last_good(s3):
    _put(s3, "nba/ml_models", "xgb_points", "OLD", "e1")
    assert mlp.predict("points", {"a": 1}) == 1.0
    s3.fail_head = True
    assert mlp.predict("points", {"a": 1}) == 1.0


WIN = {"features": ["elo_diff"], "split": "chronological", "test_mae": 9.0, "baseline_test_mae": 10.0}


def test_spread_loader_no_sticky_failure(s3):
    assert smp.model_available() is False  # nothing uploaded yet
    _put(s3, "nba/ml_models", "xgb_spread", "OLD", "e1", WIN)
    assert smp.model_available() is True
    assert smp.get_model_version() is None  # no manifest, no metadata version


def test_spread_ignored_model_is_replaced_by_a_passing_upload(s3):
    _put(s3, "nba/ml_models", "xgb_spread", "OLD", "e1", {**WIN, "test_mae": 11.0})
    assert smp.model_available() is False  # does not beat Elo
    _put(s3, "nba/ml_models", "xgb_spread", "NEW", "e2", WIN)
    assert smp.model_available() is True
    assert smp.predict_margin({"elo_diff": 1.0}) == 2.0


def test_spread_version_prefers_manifest(s3):
    _put(s3, "nba/ml_models", "xgb_spread", "OLD", "e1", {**WIN, "model_version": "m"})
    s3.put("nba/ml_models/xgb_spread_manifest.json", json.dumps({"version": "xgb-9"}).encode(), "e1")
    smp.model_available()
    assert smp.get_model_version() == "xgb-9"


def test_totals_loader_no_sticky_failure_and_refresh(s3, monkeypatch):
    monkeypatch.delenv("NBA_TOTALS_MODEL_LOCAL", raising=False)
    assert tml.model_available() is False
    _put(s3, "nba/ml_models", "gbm_totals_residual", "OLD", "e1")
    assert tml.model_available() is True
    assert tml.predict_residual({"a": 1}) == 1.0
    _put(s3, "nba/ml_models", "gbm_totals_residual", "NEW", "e2")
    assert tml.predict_residual({"a": 1}) == 2.0
