"""promote_gate: line evidence, beat-the-line, beat-the-champion, and S3 outcome helpers."""

from __future__ import annotations

import json
import pickle

import numpy as np
import pandas as pd
import pytest

from app.services.ml import model_store, promote_gate as pg, upload_to_s3
from tests.fake_s3 import FakeS3

N = 600


def _data(n=N, seed=0, n_dates=30):
    rng = np.random.default_rng(seed)
    line = rng.integers(4, 14, n) + 0.5
    signal = rng.normal(0, 1.5, n)
    actual = line + signal + rng.normal(0, 2.0, n)
    dates = np.arange(n) % n_dates
    return line, signal, actual, dates, rng


def test_promotes_when_beating_line_and_champion():
    line, signal, actual, dates, _ = _data()
    cand = line + signal
    champ = line + 0.3 * signal  # clearly worse than the candidate
    g = pg.promote_gate(cand, actual, line, dates=dates, champion_pred=champ)
    assert g["passes"] and g["status"] == "pass" and g["reason"] is None
    assert g["champion"]["gain"] > g["champion"]["required_gain"] > 0
    json.dumps(g)


def test_rejects_candidate_barely_better_than_champion():
    line, signal, actual, dates, _ = _data()
    champ = line + signal
    cand = actual * 0.001 + champ * 0.999  # ~0.1% closer to the truth
    g = pg.promote_gate(cand, actual, line, dates=dates, champion_pred=champ)
    assert g["status"] == "rejected_by_champion" and g["reason"] == "gain_below_noise"
    assert g["champion_below_line"] is False


def test_rejects_worse_than_line_and_records_champion_below_line():
    line, _, actual, dates, rng = _data()
    cand = line + rng.normal(0, 4.0, N)
    champ = line + rng.normal(0, 4.0, N)
    g = pg.promote_gate(cand, actual, line, dates=dates, champion_pred=champ)
    assert g["status"] == "rejected_by_line_gate" and g["reason"] == "worse_than_line"
    assert g["candidate_below_line"] is True and g["champion_below_line"] is True


def test_no_line_evidence_rows_and_dates():
    line, signal, actual, dates, _ = _data(n=100)
    g = pg.promote_gate(line + signal, actual, line, dates=dates)
    assert g["status"] == "no_line_evidence" and g["n_lined"] == 100
    line, signal, actual, dates, _ = _data(n_dates=5)
    g = pg.promote_gate(line + signal, actual, line, dates=dates)
    assert g["status"] == "no_line_evidence" and g["n_lined_dates"] == 5
    nolines = np.full(N, np.nan)
    assert pg.promote_gate(actual, actual, nolines)["status"] == "no_line_evidence"


def test_noise_level_improvement_rejected():
    line, signal, actual, dates, rng = _data()
    champ = line + signal
    cand = champ + rng.normal(0, 0.05, N)
    g = pg.promote_gate(cand, actual, line, dates=dates, champion_pred=champ)
    assert g["status"] == "rejected_by_champion"


def test_champion_not_comparable_passes_on_line():
    line, signal, actual, dates, _ = _data()
    champ = np.full(N, np.nan)
    champ[:49] = line[:49]
    g = pg.promote_gate(line + signal, actual, line, dates=dates, champion_pred=champ)
    assert g["passes"] and g["reason"] == "champion_not_comparable"
    assert g["champion"]["comparable"] is False and g["champion"]["n"] == 49


def test_min_slope_t_rejects_unrelated_edge():
    line, signal, actual, dates, rng = _data()
    cand = line + rng.permutation(0.1 * signal)  # small: stays within tolerance
    g = pg.promote_gate(cand, actual, line, dates=dates, min_slope_t=1.645)
    assert (
        g["status"] == "rejected_by_line_gate" and g["reason"] == "edge_not_predictive"
    )
    real = pg.promote_gate(
        line + 0.5 * signal, actual, line, dates=dates, min_slope_t=1.645
    )
    assert real["passes"]


def test_line_tolerance():
    line, _, actual, dates, _ = _data()
    mae = np.mean(np.abs(actual - line))
    # Shrink toward the line until the model MAE is a chosen fraction above it.
    for worse, expect in ((0.003, True), (0.01, False)):
        cand = line.copy()
        lo, hi = 0.0, 5.0
        for _ in range(60):  # bisect a constant offset to hit the target MAE
            mid = (lo + hi) / 2
            m = np.mean(np.abs(actual - (line + mid)))
            lo, hi = (mid, hi) if m < mae * (1 + worse) else (lo, mid)
        cand = line + lo
        assert abs(np.mean(np.abs(actual - cand)) / mae - 1 - worse) < 5e-4
        g = pg.promote_gate(cand, actual, line, dates=dates)
        assert g["passes"] is expect


def test_exit_code_table():
    for s in pg.OK_STATUSES | pg.GATE_OUTCOMES:
        assert pg.exit_code(s) == 0
    for s in ("error", "insufficient_data", None):
        assert pg.exit_code(s) == 1


def test_format_gate_line():
    line, signal, actual, dates, _ = _data()
    g = pg.promote_gate(line + signal, actual, line, dates=dates)
    out = pg.format_gate_line("NBA rebounds", g)
    assert (
        out.startswith("NBA rebounds gate: n_lined=600 dates=30") and "-> pass" in out
    )
    assert "champion_mae=n/a" in out


def test_record_and_read_outcome_round_trip():
    s3 = FakeS3()
    key = "nba/ml_models/xgb_points.pkl"
    assert pg.outcome_key(key) == "nba/ml_models/xgb_points_gate.json"
    assert pg.read_outcome(key, s3=s3) is None
    line, signal, actual, dates, _ = _data()
    g = pg.promote_gate(line + signal, actual, line, dates=dates)
    assert pg.record_outcome(key, g, extra={"stat": "points"}, s3=s3) == pg.outcome_key(
        key
    )
    back = pg.read_outcome(key, s3=s3)
    assert back["status"] == "pass" and back["stat"] == "points" and back["recorded_at"]


class _Linear:
    def predict(self, X):
        return X["a"].to_numpy() * 2 + X["b"].to_numpy()


def test_live_predictions(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(model_store.boto3, "client", lambda *a, **k: fake)
    X = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, np.nan]})
    assert upload_to_s3.live_predictions("m/x.pkl", "m/x_metadata.json", X) is None
    fake.put("m/x.pkl", pickle.dumps(_Linear()), "e1")
    with pytest.raises(ValueError):
        upload_to_s3.live_predictions("m/x.pkl", "m/x_metadata.json", X)
    fake.put(
        "m/x_metadata.json", json.dumps({"feature_names": ["a", "b"]}).encode(), "e1"
    )
    pred = upload_to_s3.live_predictions("m/x.pkl", "m/x_metadata.json", X)
    assert pred.tolist() == [5.0, 4.0]  # NaN filled with 0
