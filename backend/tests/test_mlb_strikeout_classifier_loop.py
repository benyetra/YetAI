"""MLB strikeout classifier: refreshing loader, gated upload, chronological split (L1/L2/L11)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from app.services.etl.mlb import classification_model as cm
from app.services.ml import model_store as ms
from tests.fake_s3 import FakeS3


def _clf_bytes(coef: float) -> bytes:
    clf = LogisticRegression()
    clf.classes_ = np.array([0, 1])
    clf.coef_ = np.array([[coef]])
    clf.intercept_ = np.array([0.0])
    buf = BytesIO()
    joblib.dump(clf, buf)
    return buf.getvalue()


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(ms.boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(ms, "REFRESH_SECONDS", 0)
    monkeypatch.setattr(cm, "_CLF", ms.S3Object(cm.S3_KEY, lambda b: joblib.load(BytesIO(b)), bucket=cm.S3_BUCKET))
    return fake


def test_loader_not_sticky_refreshes_and_ignores_local_file(s3, tmp_path, monkeypatch):
    local = tmp_path / "strikeout_model.pkl"
    local.write_bytes(_clf_bytes(9.0))  # a stale local copy must not be trusted
    monkeypatch.setattr(cm, "MODEL_LOCAL_PATH", str(local))
    assert cm.load_classifier() is None  # nothing in S3 yet, no local fallback
    s3.put(cm.S3_KEY, _clf_bytes(1.0), "e1")
    assert cm.load_classifier().coef_[0][0] == 1.0
    s3.put(cm.S3_KEY, _clf_bytes(2.0), "e2")
    assert cm.load_classifier().coef_[0][0] == 2.0  # retrain reaches a running worker
    s3.fail_head = True
    assert cm.load_classifier().coef_[0][0] == 2.0  # S3 blip keeps last good


def test_serving_getter_does_not_cache_a_missing_model(s3):
    from app.services.etl.mlb import strikeouts as ko

    assert ko._get_over_under_classifier() is None
    s3.put(cm.S3_KEY, _clf_bytes(1.0), "e1")
    assert ko._get_over_under_classifier() is not None


def _df(n=200):
    rng = np.random.default_rng(0)
    d = pd.DataFrame(
        {
            "date": pd.date_range("2026-04-01", periods=n),
            "projected_strikeouts": rng.normal(6, 1, n),
            "proj_ip": 5.5,
            "proj_ab": 22.0,
            "threshold": 5.5,
            "matchup_factor": 1.0,
            "days_rest": 5.0,
            "park_factor": 1.0,
        }
    )
    d["proj_minus_line"] = d["projected_strikeouts"] - d["threshold"]
    d["over_label"] = (rng.random(n) < 0.5).astype(int)
    return d.sample(frac=1.0, random_state=1)  # shuffled input order


def test_split_is_chronological_holdout_is_newest():
    df = _df()
    seen = {}

    class Spy:
        def __init__(self, est, cv="prefit"):
            self.est = est

        def fit(self, X, y):
            seen["cal"] = X.index
            return self

        def score(self, X, y):
            return 0.5

        def predict_proba(self, X):
            return np.full((len(X), 2), 0.5)

    with patch.object(cm, "CalibratedClassifierCV", Spy):
        _, X_hold, _ = cm._train_classifier(df)
    ordered = df.sort_values("date")
    assert list(X_hold.index) == list(ordered.index[int(len(df) * 0.8) :])
    assert df.loc[X_hold.index, "date"].min() > df.loc[seen["cal"], "date"].max()


def test_days_rest_uses_all_graded_starts():
    df = pd.DataFrame(
        {"date": pd.to_datetime(["2026-05-10"]), "pitcher_id": ["p1"]}
    )
    starts = [
        (pd.Timestamp("2026-05-05").date(), "p1"),  # no projection row, still a start
        (pd.Timestamp("2026-05-10").date(), "p1"),
    ]
    res = MagicMock()
    res.fetchall.return_value = starts
    res.keys.return_value = ["date", "pitcher_id"]
    with patch.object(cm.db_session, "execute", return_value=res):
        assert cm._days_rest(df).tolist() == [5]  # joined-rows-only diff gave 7


def _patched_train(monkeypatch, brier):
    X = pd.DataFrame({"projected_strikeouts": [1.0, 2.0]})
    y = pd.Series([0, 1])
    clf = LogisticRegression().fit(pd.DataFrame({"projected_strikeouts": [0.0, 1.0, 2.0, 3.0]}), [0, 0, 1, 1])
    monkeypatch.setattr(cm, "load_training_data", lambda: pd.DataFrame({"a": [1]}))
    monkeypatch.setattr(cm, "_train_classifier", lambda df: (clf, X, y))
    monkeypatch.setattr(cm, "_brier", lambda c, X, y: brier(c))
    return clf


def test_gated_upload_rejects_worse_candidate(s3, monkeypatch):
    live = _clf_bytes(1.0)
    s3.put(cm.S3_KEY, live, "e1")
    live_obj = joblib.load(BytesIO(live))
    _patched_train(monkeypatch, lambda c: 0.20 if c is live_obj else 0.30)
    monkeypatch.setattr(cm.joblib, "load", lambda f: live_obj)
    out = cm.train_and_persist()
    assert out["status"] == "rejected_by_champion"
    assert out["metric_name"] == "holdout_brier"
    assert s3.objects[cm.S3_KEY] == live  # untouched
    assert not s3.names("put")


def test_gated_upload_first_upload_and_better_candidate(s3, monkeypatch):
    _patched_train(monkeypatch, lambda c: 0.2)
    assert cm.train_and_persist()["status"] == "first_upload"
    assert cm.S3_KEY in s3.objects and "mlb/strikeout_model_manifest.json" in s3.objects
    assert cm.train_and_persist()["status"] == "uploaded"  # equal metric is not worse
