"""WNBA loaders pick up a newly uploaded model and do not fail stickily (L1)."""

from __future__ import annotations

import json
import pickle

import pytest

from app.services.etl.wnba import _ml_predict as mlp
from app.services.etl.wnba import _spread_ml_predict as smp
from app.services.etl.wnba import totals_ml as tml
from app.services.ml import model_store as ms
from tests.fake_s3 import FakeS3


class Model:
    def __init__(self, tag):
        self.tag = tag

    def predict(self, X):
        return [1.0 if self.tag == "OLD" else 2.0]


def _put(s3, name, tag, etag, meta=None):
    s3.put(f"wnba/ml_models/{name}.pkl", pickle.dumps(Model(tag)), etag)
    s3.put(
        f"wnba/ml_models/{name}_metadata.json",
        json.dumps(meta or {"features": ["a"]}).encode(),
        etag,
    )


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(ms.boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(ms, "REFRESH_SECONDS", 0)
    monkeypatch.setattr(mlp, "_OBJECTS", {})
    monkeypatch.setattr(smp, "_OBJECTS", None)
    monkeypatch.setattr(tml, "_OBJECTS", None)
    monkeypatch.delenv("WNBA_TOTALS_MODEL_LOCAL", raising=False)
    return fake


def test_prop_model_failure_is_not_sticky_and_refreshes(s3):
    with pytest.raises(RuntimeError):
        mlp.predict("points", {"a": 1})  # nothing uploaded yet
    _put(s3, "xgb_points", "OLD", "e1")
    assert mlp.predict("points", {"a": 1}) == 1.0
    _put(s3, "xgb_points", "NEW", "e2")
    assert mlp.predict("points", {"a": 1}) == 2.0  # same process, no restart


def test_prop_model_s3_blip_keeps_last_good(s3):
    _put(s3, "xgb_points", "OLD", "e1")
    assert mlp.predict("points", {"a": 1}) == 1.0
    s3.fail_head = True
    assert mlp.predict("points", {"a": 1}) == 1.0


SPREAD = {"features": ["elo_diff"], "validation": {"passes_gate": True}}


def test_spread_loader_no_sticky_failure_and_refresh(s3):
    assert smp.model_available() is False
    _put(s3, "xgb_spread", "OLD", "e1", SPREAD)
    assert smp.model_available() is True
    assert smp.predict_margin({"elo_diff": 1.0}) == 1.0
    _put(s3, "xgb_spread", "NEW", "e2", SPREAD)
    assert smp.predict_margin({"elo_diff": 1.0}) == 2.0


def test_spread_version_prefers_manifest(s3):
    _put(s3, "xgb_spread", "OLD", "e1", {**SPREAD, "model_version": "m"})
    assert smp.get_model_version() == "m"
    s3.put("wnba/ml_models/xgb_spread_manifest.json", json.dumps({"version": "xgb-9"}).encode(), "e2")
    _put(s3, "xgb_spread", "NEW", "e3", {**SPREAD, "model_version": "m"})
    assert smp.get_model_version() == "xgb-9"


def test_totals_loader_no_sticky_failure_and_refresh(s3):
    assert tml.model_available() is False
    _put(s3, "gbm_totals_residual", "OLD", "e1")
    assert tml.model_available() is True
    assert tml.predict_residual({"a": 1}) == 1.0
    _put(s3, "gbm_totals_residual", "NEW", "e2")
    assert tml.predict_residual({"a": 1}) == 2.0


def test_prop_metadata_version_comes_from_manifest(s3):
    _put(s3, "xgb_points", "OLD", "e1", meta={"features": ["a"], "model_version": "old"})
    s3.put(
        "wnba/ml_models/xgb_points_manifest.json",
        json.dumps({"version": "xgb-202611130000"}).encode(),
        "e1",
    )
    assert mlp.get_metadata("points")["model_version"] == "xgb-202611130000"
