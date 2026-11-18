"""NBA prop retrain through the promote gate, and the CLI exit codes."""

from __future__ import annotations

import json
import pickle
from datetime import date

import boto3
import numpy as np
import pandas as pd
import pytest

from app.services.etl.nba.ml_training import __main__ as props_cli
from app.services.etl.nba.ml_training import run_train_props
from app.services.etl.nba.residual import __main__ as resid_cli
from tests.fake_s3 import FakeS3

LIVE = "nba/ml_models/xgb_rebounds.pkl"
LIVE_META = "nba/ml_models/xgb_rebounds_metadata.json"
GATE_JSON = "nba/ml_models/xgb_rebounds_gate.json"
N = 1000


class _Const:
    """Stand-in live model: predicts the same number for every row."""

    def predict(self, X):
        return np.full(len(X), 6.0)


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3(
        {LIVE: pickle.dumps(_Const()), LIVE_META: b'{"feature_names": ["x1", "x2"]}'}
    )
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    return fake


def _setup(monkeypatch, line_noise):
    """Daily rows; target is predictable from x1. ``line_noise`` None -> line equals
    the actual (unbeatable), a number -> actual plus that much noise, 'none' -> no lines.
    """
    rng = np.random.default_rng(3)
    x1 = rng.normal(size=N)
    f = pd.DataFrame({"x1": x1, "x2": rng.normal(size=N)})
    t = pd.Series(np.clip(6 + 1.5 * x1 + rng.normal(0, 0.5, N), 1, None))
    dates = pd.date_range("2024-01-01", periods=N)
    keys = [(i % 7, d.date()) for i, d in enumerate(dates)]
    f.attrs["keys"] = keys
    monkeypatch.setattr(
        run_train_props.build_training_dataset, "build", lambda *a: (f, t)
    )
    if line_noise == "none":
        line = np.full(N, np.nan)
    elif line_noise is None:
        line = t.to_numpy()
    else:
        line = np.clip(t.to_numpy() + rng.normal(0, line_noise, N), 1, None)
    lines = pd.DataFrame(
        {"player_id": [k[0] for k in keys], "date": dates, "line": line}
    ).dropna()
    monkeypatch.setattr(run_train_props, "_load_lines", lambda *a: lines)


def _run(upload=True):
    return run_train_props.run(
        "rebounds",
        season_start=date(2024, 1, 1),
        season_end=date(2026, 9, 26),
        upload=upload,
    )


def test_worse_than_line_is_rejected_and_nothing_uploaded(monkeypatch, s3):
    _setup(monkeypatch, None)
    out = _run()
    assert out["status"] == "rejected_by_line_gate" and "gate" not in out
    assert pickle.loads(s3.objects[LIVE]).__class__ is _Const  # live model untouched
    assert not any(c[0] == "copy" for c in s3.calls)
    rec = json.loads(s3.objects[GATE_JSON])
    assert rec["status"] == "rejected_by_line_gate" and rec["stat"] == "rebounds"
    assert rec["candidate_below_line"] is True and rec["champion"]["comparable"]


def test_beats_line_and_champion_is_uploaded(monkeypatch, s3):
    _setup(monkeypatch, 2.5)
    out = _run()
    assert out["status"] == "ok", out
    assert out["gate"]["status"] == "uploaded"
    assert out["s3_keys"]["model_key"] == LIVE
    assert pickle.loads(s3.objects[LIVE]).__class__ is not _Const
    assert json.loads(s3.objects[GATE_JSON])["passes"] is True
    manifest = json.loads(s3.objects["nba/ml_models/xgb_rebounds_manifest.json"])
    assert manifest["line_gate"]["status"] == "pass"
    assert (
        out["metadata"]["line_comparison"] == out["metadata"]["promote_gate"]["lined"]
    )


def test_marginal_gain_over_champion_is_rejected(monkeypatch, s3):
    _setup(monkeypatch, 2.5)
    trained = []
    real = run_train_props.train_model.train
    monkeypatch.setattr(
        run_train_props.train_model,
        "train",
        lambda *a, **k: trained.append(real(*a, **k)) or trained[-1],
    )
    # live model = the candidate's own predictions plus 0.0001: a 0.01% gain
    monkeypatch.setattr(
        run_train_props.ml_upload,
        "live_prop_predictions",
        lambda cfg, stat, X: trained[0][0].predict(X) + 1e-4,
    )
    out = _run()
    assert (
        out["status"] == "rejected_by_champion" and out["reason"] == "gain_below_noise"
    )
    assert pickle.loads(s3.objects[LIVE]).__class__ is _Const
    assert json.loads(s3.objects[GATE_JSON])["status"] == "rejected_by_champion"


def test_no_lines_is_no_line_evidence_never_a_pass(monkeypatch, s3):
    _setup(monkeypatch, "none")
    out = _run()
    assert out["status"] == "no_line_evidence"
    assert json.loads(s3.objects[GATE_JSON])["status"] == "no_line_evidence"
    # a loading error is the same outcome, and is reported
    monkeypatch.setattr(
        run_train_props,
        "_load_lines",
        lambda *a: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    out = _run()
    assert out["status"] == "no_line_evidence"
    assert out["metadata"]["line_error"] == "db down"


def test_dry_run_gates_without_s3(monkeypatch):
    _setup(monkeypatch, 2.5)
    monkeypatch.setattr(boto3, "client", lambda *a, **k: pytest.fail("S3 touched"))
    out = _run(upload=False)
    assert out["status"] == "ok" and out["metadata"]["promote_gate"]["passes"]


def test_unreadable_champion_raises(monkeypatch, s3):
    _setup(monkeypatch, 2.5)
    del s3.objects[LIVE_META]
    with pytest.raises(ValueError, match="metadata"):
        _run()


@pytest.mark.parametrize(
    "status, code",
    [
        ("ok", 0),
        ("dry_run", 0),
        ("rejected_by_line_gate", 0),
        ("rejected_by_champion", 0),
        ("no_line_evidence", 0),
        ("insufficient_data", 1),
    ],
)
def test_props_cli_exit_codes(monkeypatch, capsys, status, code):
    monkeypatch.setattr(props_cli, "run", lambda *a, **k: {"status": status})
    argv = ["--stat", "points", "--start", "2024-01-01", "--end", "2024-02-01"]
    assert props_cli.main(argv) == code
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_props_cli_error_is_one_json_line_and_exit_1(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("champion exploded")

    monkeypatch.setattr(props_cli, "run", boom)
    argv = ["--stat", "points", "--start", "2024-01-01", "--end", "2024-02-01"]
    assert props_cli.main(argv) == 1
    cap = capsys.readouterr()
    assert cap.out == "" and json.loads(cap.err)["error"] == "champion exploded"


@pytest.mark.parametrize(
    "status, code", [("rejected_by_line_gate", 0), ("ok", 0), ("insufficient_data", 1)]
)
def test_residual_cli_exit_codes(monkeypatch, capsys, status, code):
    monkeypatch.setattr(resid_cli.trainer, "train", lambda *a, **k: {"status": status})
    argv = [
        "train",
        "--stat",
        "rebounds",
        "--start",
        "2024-01-01",
        "--end",
        "2024-02-01",
    ]
    assert resid_cli.main(argv) == code
    assert json.loads(capsys.readouterr().out)["status"] == status
