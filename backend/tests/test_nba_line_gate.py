"""Beats-the-line gate, its hard use in gated_upload, and the retrain's line_comparison."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.services.etl.nba.ml_training import run_train_props
from app.services.etl.nba.residual.gate import beats_line_gate, line_comparison
from app.services.ml import model_store
from tests.fake_s3 import FakeS3


def _synthetic(n=400, seed=0):
    rng = np.random.default_rng(seed)
    line = rng.integers(4, 14, n) + 0.5
    signal = rng.normal(0, 1.5, n)
    actual = line + signal + rng.normal(0, 2.0, n)
    return line, signal, actual, rng


def test_gate_accepts_model_that_beats_line():
    line, signal, actual, _ = _synthetic()
    g = beats_line_gate(0.5 * signal, actual, line)
    assert g["passes"] and g["failed"] == [] and g["slope"] > 0 and g["n"] == 400


def test_gate_rejects_worse_than_line():
    line, _, actual, rng = _synthetic()
    g = beats_line_gate(rng.normal(0, 4.0, 400), actual, line)
    assert not g["passes"] and "worse_than_line" in g["failed"]


def test_gate_rejects_unrelated_edge():
    line, signal, actual, rng = _synthetic()
    g = beats_line_gate(rng.permutation(0.5 * signal), actual, line)
    assert not g["passes"] and "edge_not_predictive" in g["failed"]


def test_gate_too_few_rows():
    line, signal, actual, _ = _synthetic(n=100)
    g = beats_line_gate(0.5 * signal, actual, line)
    assert not g["passes"] and "too_few_rows" in g["failed"]


def test_line_comparison_filters_and_degrades():
    out = line_comparison([5, np.nan, 5, 6], [6, 6, 6, 6], [4.5, 4.5, 0, 6.5])
    assert out["n"] == 2 and out["side_n"] == 2
    assert line_comparison([1], [1], [1])["slope"] is None


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(model_store.boto3, "client", lambda *a, **k: fake)
    return fake


def _up(**kw):
    return model_store.gated_upload(
        "nba/ml_models/m.pkl",
        b"x",
        candidate_metric=1.0,
        metric_name="mae",
        score_champion=lambda b: 5.0,
        **kw,
    )


def test_failing_line_gate_makes_no_s3_calls(s3):
    out = _up(line_gate={"passes": False, "failed": ["worse_than_line"]})
    assert out["status"] == "rejected_by_line_gate" and s3.calls == []


def test_passing_line_gate_lands_in_manifest_and_none_is_unchanged(s3):
    assert _up(line_gate={"passes": True, "failed": []})["status"] == "first_upload"
    m = json.loads(s3.objects["nba/ml_models/m_manifest.json"])
    assert m["line_gate"]["passes"] is True
    s3.objects.clear()
    _up()
    assert "line_gate" not in json.loads(s3.objects["nba/ml_models/m_manifest.json"])


def test_retrain_metadata_carries_line_comparison(monkeypatch):
    rng = np.random.default_rng(1)
    n = 200
    f = pd.DataFrame({"rebounds_avg_5": rng.normal(6, 2, n), "x": rng.normal(0, 1, n)})
    t = pd.Series(f["rebounds_avg_5"] + rng.normal(0, 1, n), name="rebounds")
    dates = pd.date_range("2026-01-01", periods=n)
    f.attrs["keys"] = [(i % 7, d.date()) for i, d in enumerate(dates)]
    monkeypatch.setattr(
        run_train_props.build_training_dataset, "build", lambda *a: (f, t)
    )
    lines = pd.DataFrame(
        {"player_id": [k[0] for k in f.attrs["keys"]], "date": dates, "line": 6.5}
    )
    monkeypatch.setattr(run_train_props, "_load_lines", lambda *a: lines)
    out = run_train_props.run(
        "rebounds", season_start=date(2026, 1, 1), season_end=date(2026, 7, 1)
    )
    lc = out["metadata"]["line_comparison"]
    assert lc["n"] == 40 and lc["model_mae"] is not None
    # no keys / unavailable lines: n == 0, retrain still completes
    f.attrs["keys"] = []
    out = run_train_props.run(
        "rebounds", season_start=date(2026, 1, 1), season_end=date(2026, 7, 1)
    )
    assert out["metadata"]["line_comparison"]["n"] == 0
