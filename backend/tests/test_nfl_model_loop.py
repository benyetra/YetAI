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


# L2 / L7 promote: NFL uploads go through the champion gate
from app.services.etl.nfl.ml_training import train_qb_model as tqm  # noqa: E402
import pandas as pd  # noqa: E402


class Yards:
    """Predicts a constant residual; tier baseline => yards = tier + c."""

    def __init__(self, c):
        self.c = c

    def predict(self, X):
        return np.array([self.c])


def _live_yards(s3, c):
    s3.put(f"{PFX}/qb_passing_yards.pkl", pickle.dumps(Yards(c)), "e0")
    meta = {"features": ["tier_yards"], "residual_target": True, "baseline_mode": "tier"}
    s3.put(f"{PFX}/qb_passing_yards_metadata.json", json.dumps(meta).encode(), "e0")


def _hold():
    X = pd.DataFrame({"tier_yards": [250.0, 260.0, 240.0, 255.0]})
    return X, np.array([250.0, 260.0, 240.0, 255.0])  # residual 0 is perfect


def test_qb_upload_rejects_worse_candidate_and_leaves_live_untouched(s3):
    _live_yards(s3, 0.0)  # live MAE 0 on this holdout
    live = s3.objects[f"{PFX}/qb_passing_yards.pkl"]
    X, y = _hold()
    out = tqm.upload_qb_model(
        Yards(30.0), {"features": ["tier_yards"]}, candidate_mae=30.0, X_hold=X, y_hold=y
    )
    assert out["status"] == "rejected_by_champion"
    assert s3.objects[f"{PFX}/qb_passing_yards.pkl"] == live
    assert not s3.names("put")


def test_qb_upload_ships_better_candidate_with_manifest_and_archive(s3):
    _live_yards(s3, 30.0)
    X, y = _hold()
    out = tqm.upload_qb_model(
        Yards(0.0), {"features": ["tier_yards"]}, candidate_mae=0.0, X_hold=X, y_hold=y
    )
    assert out["status"] == "uploaded"
    assert json.loads(s3.objects[f"{PFX}/qb_passing_yards_manifest.json"])["version"].startswith("gbm-qb-")
    assert out["archive_stamp"]
    assert f"{PFX}/qb_passing_yards_metadata.json" in s3.objects


def _ou_hold():
    return pd.DataFrame({"tier_yards": [1.0, 2.0, 3.0, 4.0]}), np.array([0, 0, 1, 1])


def _live_ou(s3, p):
    s3.put(f"{PFX}/qb_pass_yds_ou.pkl", pickle.dumps(Clf(p)), "e0")
    s3.put(f"{PFX}/qb_pass_yds_ou_metadata.json", json.dumps({"features": ["tier_yards"]}).encode(), "e0")


def test_ou_upload_requires_brier_under_coin_flip(s3):
    X, y = _ou_hold()
    for brier in (0.25, 0.3, None):
        meta = {"holdout_brier": brier} if brier is not None else {}
        out = tqm.upload_ou_model(Clf(0.5), meta, X_hold=X, y_hold=y)
        assert out["status"] == "rejected_coin_flip"
    assert not s3.names("put")


class Smart:
    """Perfect-ish on _ou_hold: P(over)=0.9 when tier_yards > 2.5 (Brier 0.01)."""

    def predict_proba(self, X):
        p = np.where(X["tier_yards"].to_numpy() > 2.5, 0.9, 0.1)
        return np.column_stack([1 - p, p])


def _live_ou_model(s3, model):
    s3.put(f"{PFX}/qb_pass_yds_ou.pkl", pickle.dumps(model), "e0")
    meta = {"features": ["tier_yards"]}
    s3.put(f"{PFX}/qb_pass_yds_ou_metadata.json", json.dumps(meta).encode(), "e0")


def test_ou_upload_blocked_when_live_classifier_is_better(s3):
    X, y = _ou_hold()
    _live_ou_model(s3, Smart())  # live Brier 0.01 on this holdout
    out = tqm.upload_ou_model(Clf(0.5), {"holdout_brier": 0.2499}, X_hold=X, y_hold=y)
    assert out["status"] == "rejected_by_champion"
    assert not s3.names("put")


def test_ou_upload_ships_when_candidate_beats_live(s3):
    X, y = _ou_hold()
    _live_ou_model(s3, Clf(0.9))  # live Brier ~0.41
    out = tqm.upload_ou_model(Clf(0.5), {"holdout_brier": 0.2499}, X_hold=X, y_hold=y)
    assert out["status"] == "uploaded"
    assert f"{PFX}/qb_pass_yds_ou_manifest.json" in s3.objects


def test_prod_eval_upload_needs_promote_and_force_still_hits_champion_gate(s3, monkeypatch, tmp_path):
    from scripts import nfl_prod_qb_eval as ev

    monkeypatch.setattr(ev, "_MODELS_DIR", tmp_path)
    (tmp_path / "qb_passing_yards.pkl").write_bytes(pickle.dumps(Yards(30.0)))
    (tmp_path / "qb_passing_yards_metadata.json").write_text(json.dumps({"features": ["tier_yards"]}))
    _live_yards(s3, 0.0)  # live is perfect on the holdout
    X, y = _hold()
    holdout = {"yards": (X, y), "yards_mae": 30.0}

    skipped = ev.maybe_upload({"promote_recommended": False}, holdout=holdout)
    assert "s3_upload_skipped" in skipped and not s3.names("put")

    forced = ev.maybe_upload({"promote_recommended": False}, force=True, holdout=holdout)
    assert forced["force_upload"] is True
    assert forced["s3_upload"]["qb_passing_yards"]["status"] == "rejected_by_champion"
    assert forced["s3_uploaded"] == {} and not s3.names("put")
