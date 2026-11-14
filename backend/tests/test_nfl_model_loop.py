"""NFL model loop: refreshing loaders, version stamp, O/U classifier gate, gated promote."""

from __future__ import annotations

import json
import pickle

import numpy as np
import pytest

from app.services.etl.nfl import qb_passing_yards_ml as qbm
from app.services.ml import model_store as ms
from tests.fake_s3 import FakeS3

PFX = "nfl/ml_models"


class Model:
    def __init__(self, tag):
        self.tag = tag

    def predict(self, X):
        return [5.0 if self.tag == "OLD" else 9.0]


def _put_qb(s3, tag, etag, **meta):
    s3.put(f"{PFX}/qb_passing_yards.pkl", pickle.dumps(Model(tag)), etag)
    m = {
        "features": ["tier_yards"],
        "residual_target": True,
        "baseline_mode": "tier",
        "target": "residual_actual_minus_baseline",
        **meta,
    }
    s3.put(f"{PFX}/qb_passing_yards_metadata.json", json.dumps(m).encode(), etag)


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(ms.boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(ms, "REFRESH_SECONDS", 0)
    monkeypatch.setenv("NFL_QB_ML_ENABLED", "1")  # prod: no bundled pickle
    monkeypatch.delenv("NFL_QB_MODEL_LOCAL", raising=False)
    monkeypatch.setattr(qbm, "_OBJECTS", None)
    monkeypatch.setattr(qbm, "_MODEL", None)
    monkeypatch.setattr(qbm, "_METADATA", None)
    monkeypatch.setattr(qbm, "_LOAD_FAILED", False)
    return fake


def test_qb_model_picks_up_new_upload_and_failure_is_not_sticky(s3):
    feats = {"tier_yards": 250.0}
    assert qbm.predict_yards_ml_loaded(feats) is None  # nothing in S3 yet
    _put_qb(s3, "OLD", "e1")
    assert qbm.predict_yards_ml_loaded(feats) == 255.0  # earlier miss not cached
    _put_qb(s3, "NEW", "e2")
    assert qbm.predict_yards_ml_loaded(feats) == 259.0  # no restart needed


def test_qb_model_keeps_last_good_when_s3_fails(s3):
    _put_qb(s3, "OLD", "e1")
    assert qbm.predict_yards_ml_loaded({"tier_yards": 250.0}) == 255.0
    s3.fail_head = True
    assert qbm.predict_yards_ml_loaded({"tier_yards": 250.0}) == 255.0


# L3: version stamp reflects the ML term
def test_version_tier_when_ml_not_applied(s3):
    assert qbm.resolve_qb_model_version(pub_method="tier", ml_yards=None) == "tier-v3"
    # ML computed but no real line -> published number is the tier
    assert qbm.resolve_qb_model_version(pub_method="tier", ml_yards=260.0) == "tier-v3"
    assert qbm.resolve_qb_model_version(pub_method="soft_anchor", ml_yards=None) == "tier-v3"


def test_version_marks_shadow_ml_soft_anchor(s3):
    _put_qb(s3, "OLD", "e1", model_version="gbm-qb-residual-20260811")
    s3.put(
        f"{PFX}/qb_passing_yards_manifest.json",
        json.dumps({"version": "xgb-202611131200"}).encode(),
        "e1",
    )
    qbm.predict_yards_ml_loaded({"tier_yards": 250.0})
    v = qbm.resolve_qb_model_version(pub_method="soft_anchor", ml_yards=260.0)
    assert v == "tier-v3-202611131200"
    assert len(v) <= 20 and v != "tier-v3"


def test_version_gbm_uses_model_version(s3):
    _put_qb(s3, "OLD", "e1", model_version="gbm-qb-residual-20260811")
    qbm.predict_yards_ml_loaded({"tier_yards": 250.0})
    assert (
        qbm.resolve_qb_model_version(pub_method="gbm", ml_yards=260.0)
        == "gbm-qb-residual-2026"[:20]
    )


# L7: O/U classifier loads from S3 first (flag on) and is gated on holdout Brier
from app.services.etl.nfl import qb_ou_classifier as ouc  # noqa: E402


class Clf:
    def __init__(self, p):
        self.p = p

    def predict_proba(self, X):
        return np.array([[1 - self.p, self.p]])


def _put_ou(s3, p, brier, etag="e1", manifest=None):
    s3.put(f"{PFX}/qb_pass_yds_ou.pkl", pickle.dumps(Clf(p)), etag)
    meta = {"features": ["tier_yards"], "holdout_brier": brier}
    s3.put(f"{PFX}/qb_pass_yds_ou_metadata.json", json.dumps(meta).encode(), etag)
    if manifest:
        s3.put(f"{PFX}/qb_pass_yds_ou_manifest.json", json.dumps(manifest).encode(), etag)


@pytest.fixture
def ou(s3, monkeypatch):
    monkeypatch.setattr(ouc, "_OBJECTS", None)
    monkeypatch.setattr(ouc, "_LOCAL", (Clf(0.55), {"features": ["tier_yards"], "holdout_brier": 0.2479}))
    monkeypatch.setattr(ouc, "_LOCAL_FAILED", False)
    return s3


def _over():
    return ouc.predict_over_probability_loaded({"tier_yards": 250.0}, 250.0)


def test_ou_prefers_s3_over_repo_pickle_when_flag_on(ou):
    _put_ou(ou, 0.9, 0.20)
    assert _over() == 0.9


def test_ou_flag_off_uses_bundled_shadow(ou, monkeypatch):
    monkeypatch.delenv("NFL_QB_ML_ENABLED")
    _put_ou(ou, 0.9, 0.20)
    assert _over() == 0.55


def test_ou_falls_back_to_repo_pickle_when_s3_empty(ou):
    assert _over() == 0.55


def test_ou_refreshes_from_s3(ou):
    _put_ou(ou, 0.9, 0.20, "e1")
    assert _over() == 0.9
    _put_ou(ou, 0.8, 0.21, "e2")
    assert _over() == 0.8


def test_ou_coin_flip_brier_not_used(ou, monkeypatch):
    _put_ou(ou, 0.9, 0.25)  # not < 0.25
    monkeypatch.setattr(ouc, "_LOCAL", None)
    monkeypatch.setattr(ouc, "_LOCAL_FAILED", True)
    assert _over() is None
    _put_ou(ou, 0.9, 0.2499, "e2")
    assert _over() == 0.9


def test_ou_manifest_brier_wins_over_metadata(ou, monkeypatch):
    monkeypatch.setattr(ouc, "_LOCAL", None)
    monkeypatch.setattr(ouc, "_LOCAL_FAILED", True)
    _put_ou(ou, 0.9, 0.20, manifest={"metric_name": "holdout_brier", "holdout_metric": 0.26})
    assert _over() is None


def test_ou_missing_brier_not_used(ou, monkeypatch):
    monkeypatch.setattr(ouc, "_LOCAL", None)
    monkeypatch.setattr(ouc, "_LOCAL_FAILED", True)
    _put_ou(ou, 0.9, None)
    assert _over() is None
