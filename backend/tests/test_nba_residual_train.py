"""Residual trainer: gate decides, upload only through the gated path."""

import json
import pickle

import numpy as np
import pandas as pd
import pytest

from app.services.etl.nba.residual import train as T
from app.services.etl.nba.residual.dataset import feature_columns
from app.services.ml import model_store
from tests.fake_s3 import FakeS3


def _rows(n_days=60, per_day=10, signal=0.0, seed=0):
    rng = np.random.default_rng(seed)
    n = n_days * per_day
    df = pd.DataFrame({c: rng.normal(size=n) for c in feature_columns()})
    f0 = df[feature_columns()[0]].to_numpy()
    df["date"] = np.repeat(pd.date_range("2026-01-01", periods=n_days), per_day)
    df["line"] = 5.5
    df["resid"] = signal * f0 + rng.normal(scale=2.0, size=n) + 0.01
    df["over"] = np.where(df["resid"] > 0, 1.0, 0.0)
    return df


def test_insufficient_data():
    out = T.train("rebounds", "2026-01-01", "2026-03-01", rows=_rows(10, 10))
    assert out["status"] == "insufficient_data" and out["n_rows"] == 100


def test_gate_failed_no_upload(monkeypatch):
    called = []
    monkeypatch.setattr(
        T.upload_to_s3, "upload_gated_pickle", lambda *a, **k: called.append(1)
    )
    s3 = FakeS3()
    out = T.train(
        "rebounds",
        "2026-01-01",
        "2026-03-01",
        rows=_rows(per_day=20),
        upload=True,
        s3=s3,
    )
    assert out["status"] == "rejected_by_line_gate" and not called
    assert not out["gate"]["passes"]
    # the rejection is recorded next to the model
    rec = json.loads(s3.objects["nba/ml_models/residual_rebounds_gate.json"])
    assert rec["status"] == "rejected_by_line_gate" and rec["stat"] == "rebounds"


def test_too_few_lined_rows_is_no_line_evidence(monkeypatch):
    out = T.train("rebounds", "2026-01-01", "2026-03-01", rows=_rows(signal=3.0))
    assert out["status"] == "no_line_evidence" and out["gate"]["n_lined"] < 150


def test_gate_pass_uploads_with_line_gate(monkeypatch):
    seen = {}

    def fake(key, model, meta, **kw):
        seen.update(key=key, meta=meta, **kw)
        return {"status": "first_upload", "champion_metric": None}

    monkeypatch.setattr(T.upload_to_s3, "upload_gated_pickle", fake)
    rows = _rows(per_day=20, signal=3.0)
    s3 = FakeS3()
    out = T.train("assists", "2026-01-01", "2026-03-01", rows=rows, upload=True, s3=s3)
    assert out["status"] == "ok", out
    rec = json.loads(s3.objects["nba/ml_models/residual_assists_gate.json"])
    assert rec["passes"] and rec["upload_status"] == "first_upload"
    assert seen["key"] == "nba/ml_models/residual_assists.pkl"
    assert seen["line_gate"]["passes"]
    assert seen["candidate_metric"] == out["holdout_mae"]
    assert seen["meta"]["train_end"] == "2026-03-01"
    # version label names the model kind, not "xgb" (review F6)
    assert seen["version_prefix"] == T.DEFAULT_KIND.replace("_", "")
    # dry without --upload
    seen.clear()
    assert (
        T.train("assists", "2026-01-01", "2026-03-01", rows=rows)["status"] == "dry"
        and not seen
    )


def test_holdout_strictly_later():
    fit_df, hold = T.split_holdout(_rows())
    assert fit_df["date"].max() < hold["date"].min()
    assert hold["date"].nunique() == 12


def test_save_local_on_gate_failure(tmp_path):
    out = T.train(
        "rebounds", "2026-01-01", "2026-03-01", rows=_rows(), save_local=tmp_path
    )
    meta = json.loads((tmp_path / "residual_rebounds_metadata.json").read_text())
    assert out["status"] == "no_line_evidence" == meta["status"]
    assert (tmp_path / "residual_rebounds.pkl").exists()


def test_champion_predictions_nan_up_to_train_end():
    rows = _rows(signal=1.0)
    fit_df, hold = T.split_holdout(rows)
    live = T.residual_model.fit(fit_df, feature_columns(), "ridge", stat="rebounds")
    objs = lambda te: {  # noqa: E731
        T.model_key("rebounds"): pickle.dumps(live),
        T._meta_key("rebounds"): json.dumps({"train_end": te}).encode(),
    }
    # live model trained through the whole holdout: nothing comparable
    out = T.champion_predictions("rebounds", hold, FakeS3(objs("2026-03-01")))
    assert np.isnan(out).all()
    # trained before it: every row is scored, as line + predicted residual
    out = T.champion_predictions("rebounds", hold, FakeS3(objs("2026-01-01")))
    pred, _ = live.predict(hold)
    assert np.allclose(out, hold["line"].to_numpy() + pred)
    # no live model, or no metadata to date it
    assert T.champion_predictions("rebounds", hold, FakeS3()) is None
    only_model = {T.model_key("rebounds"): pickle.dumps(live)}
    assert T.champion_predictions("rebounds", hold, FakeS3(only_model)) is None


def test_inf_champion_does_not_block_upload(monkeypatch):
    s3 = FakeS3({"nba/ml_models/residual_rebounds.pkl": b"x"})
    monkeypatch.setattr(model_store.boto3, "client", lambda *a, **k: s3)
    out = model_store.gated_upload(
        "nba/ml_models/residual_rebounds.pkl",
        b"new",
        candidate_metric=1.0,
        metric_name="holdout_mae",
        score_champion=lambda b: float("inf"),
    )
    assert out["status"] == "uploaded"
