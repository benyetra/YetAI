"""WNBA props and NHL shots/saves use the shared line gate before any upload."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services.etl.nhl import goalie_saves_ml as gsm
from app.services.etl.nhl import player_shots_ml as psm
from app.services.etl.nhl.ml_training import train_goalie_model as tg
from app.services.etl.nhl.ml_training import train_player_shots_model as tp
from app.services.etl.wnba.ml_training import __main__ as wnba_cli
from app.services.etl.wnba.ml_training import run_train_props
from app.services.ml import model_store
from tests.fake_s3 import FakeS3

WINDOW = dict(season_start=date(2025, 5, 1), season_end=date(2025, 9, 30))
N = 800  # holdout = 160 rows, above the gate's 150-lined-row minimum


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(model_store.boto3, "client", lambda *_a, **_k: fake)
    return fake


# ---- WNBA ---------------------------------------------------------------------------


def _wnba(monkeypatch, line_noise, offset=0.0):
    """Props frame with keys; stored line = actual + offset + noise (None: no lines)."""
    rng = np.random.default_rng(0)
    x = rng.normal(15, 5, N)
    feats = pd.DataFrame({"points_l5": x, "minutes_l5": rng.normal(28, 4, N)})
    target = pd.Series(0.7 * x + rng.normal(0, 3, N), name="points")
    keys = [(i % 50, date(2025, 5, 1) + timedelta(days=i // 8)) for i in range(N)]
    feats.attrs["keys"] = keys
    monkeypatch.setattr(
        run_train_props.build_training_dataset, "build", lambda *a: (feats, target)
    )
    if line_noise is None:
        lines = pd.DataFrame({"player_id": [], "date": [], "line": []})
    else:
        lines = pd.DataFrame(
            {
                "player_id": [k[0] for k in keys],
                "date": pd.to_datetime([k[1] for k in keys]),
                "line": target.to_numpy() + offset + rng.normal(0, line_noise, N),
            }
        )
    monkeypatch.setattr(run_train_props, "_load_lines", lambda *a: lines)


def test_wnba_worse_than_line_is_not_uploaded(s3, monkeypatch):
    _wnba(monkeypatch, line_noise=0.05)  # the line is almost the truth
    out = run_train_props.run("points", upload=True, **WINDOW)
    assert out["status"] == "rejected_by_line_gate"
    assert "s3_keys" not in out
    assert "wnba/ml_models/xgb_points.pkl" not in s3.objects
    assert "wnba/ml_models/xgb_points_gate.json" in s3.objects  # outcome recorded
    assert wnba_cli.exit_code(out["status"]) == 0


def test_wnba_clearly_better_than_line_uploads(s3, monkeypatch):
    _wnba(monkeypatch, line_noise=8.0, offset=30.0)  # a line well off the truth
    out = run_train_props.run("points", upload=True, **WINDOW)
    assert out["status"] == "ok" and out["promote_gate"]["passes"]
    assert out["gate"]["status"] == "first_upload"
    assert "wnba/ml_models/xgb_points.pkl" in s3.objects


def test_wnba_no_stored_lines_is_no_line_evidence(s3, monkeypatch):
    _wnba(monkeypatch, line_noise=None)
    out = run_train_props.run("points", upload=True, **WINDOW)
    assert out["status"] == "no_line_evidence"
    assert "wnba/ml_models/xgb_points.pkl" not in s3.objects


def test_wnba_builder_without_keys_gates_on_no_line_evidence(s3, monkeypatch):
    _wnba(monkeypatch, line_noise=8.0, offset=30.0)
    feats, target = run_train_props.build_training_dataset.build()
    feats.attrs.clear()  # today's WNBA builder never sets attrs["keys"]
    out = run_train_props.run("points", upload=True, **WINDOW)
    assert out["status"] == "no_line_evidence"
    assert "wnba/ml_models/xgb_points.pkl" not in s3.objects


# ---- NHL ----------------------------------------------------------------------------


class Col:
    """Candidate model whose prediction is the column ``col`` of the holdout."""

    def __init__(self, col):
        self.col = col

    def predict(self, X):
        return X[self.col].to_numpy()


CASES = {
    "shots": (psm, tp, "upload_player_shots_model", "shots_line"),
    "saves": (gsm, tg, "upload_goalie_model", "saves_line"),
}


def _holdout(mod, line_col, cand_noise, line_noise):
    rng = np.random.default_rng(1)
    y = pd.Series(rng.normal(20, 4, 200))
    X = pd.DataFrame({c: 0.0 for c in mod.feature_names()}, index=range(200))
    X[line_col] = (y + rng.normal(0, line_noise, 200)) if line_noise else 0.0
    X["cand"] = y + rng.normal(0, cand_noise, 200)
    return X, y


@pytest.mark.parametrize("name", CASES)
def test_nhl_worse_than_line_is_not_uploaded(name, s3):
    mod, trainer, upload, line_col = CASES[name]
    X, y = _holdout(mod, line_col, cand_noise=6.0, line_noise=1.0)
    out = getattr(trainer, upload)(Col("cand"), {"holdout_mae": 4.0}, X, y)
    assert out["status"] == "rejected_by_line_gate"
    assert f"{mod.S3_PREFIX}/{mod.MODEL_KEY}.pkl" not in s3.objects
    assert f"{mod.S3_PREFIX}/{mod.MODEL_KEY}_gate.json" in s3.objects


@pytest.mark.parametrize("name", CASES)
def test_nhl_clearly_better_than_line_uploads(name, s3):
    mod, trainer, upload, line_col = CASES[name]
    X, y = _holdout(mod, line_col, cand_noise=0.5, line_noise=4.0)
    out = getattr(trainer, upload)(Col("cand"), {"holdout_mae": 0.4}, X, y)
    assert out["status"] == "first_upload"
    assert f"{mod.S3_PREFIX}/{mod.MODEL_KEY}.pkl" in s3.objects


@pytest.mark.parametrize("name", CASES)
def test_nhl_no_lines_is_no_line_evidence(name, s3):
    mod, trainer, upload, line_col = CASES[name]
    X, y = _holdout(mod, line_col, cand_noise=0.5, line_noise=0)
    out = getattr(trainer, upload)(Col("cand"), {"holdout_mae": 0.4}, X, y)
    assert out["status"] == "no_line_evidence"
    assert f"{mod.S3_PREFIX}/{mod.MODEL_KEY}.pkl" not in s3.objects


def test_nhl_run_reports_the_gate_status(s3, monkeypatch):
    rng = np.random.default_rng(2)
    X = pd.DataFrame(
        rng.normal(0, 1, (100, len(psm.feature_names()))), columns=psm.feature_names()
    )
    X["shots_line"] = 0.0  # no stored lines
    monkeypatch.setattr(tp, "build", lambda *a: (X, pd.Series(rng.normal(3, 1, 100))))
    out = tp.run(upload=True, **WINDOW)
    assert out["status"] == "no_line_evidence"
    assert tp.exit_code(out["status"]) == 0


def test_nhl_candidate_not_beating_the_live_model_is_rejected(s3):
    import json
    import pickle

    mod, trainer, upload, line_col = CASES["shots"]
    X, y = _holdout(mod, line_col, cand_noise=0.5, line_noise=4.0)
    X["live"] = y + np.random.default_rng(3).normal(0, 0.5, len(y))  # as good as it
    pkl, meta = f"{mod.S3_PREFIX}/{mod.MODEL_KEY}.pkl", None
    s3.put(pkl, pickle.dumps(Col("live")), "e1")
    s3.put(
        f"{mod.S3_PREFIX}/{mod.MODEL_KEY}_metadata.json",
        json.dumps({"features": list(X.columns)}).encode(),
        "e1",
    )
    out = getattr(trainer, upload)(Col("cand"), {"holdout_mae": 0.4}, X, y)
    assert out["status"] == "rejected_by_champion"
    assert pickle.loads(s3.objects[pkl]).col == "live"


def test_wnba_builder_returns_keys_for_line_join(monkeypatch):
    """The WNBA builder must carry (player_id, game_date) per row, or the gate
    can never find a line and every retrain is ``no_line_evidence``."""
    from types import SimpleNamespace

    from app.services.etl.wnba.ml_training import build_training_dataset as B

    rows = [
        SimpleNamespace(
            player_id=p, game_date=date(2026, 6, d), opponent_team_id=1, points=pts
        )
        for p, d, pts in [(1, 1, 10.0), (2, 1, None), (3, 2, 8.0), (4, 2, 7.0)]
    ]

    class Q:
        def filter(self, *a):
            return self

        def order_by(self, *a):
            return self

        def all(self):
            return rows

    db = SimpleNamespace(query=lambda *a: Q(), close=lambda: None)
    monkeypatch.setattr(B, "SessionLocal", lambda: db)
    monkeypatch.setattr(B, "load_training_context", lambda *a: None)
    # player 4 has too little history: the builder skips him
    monkeypatch.setattr(
        B,
        "build_features",
        lambda db, **kw: None if kw["player_id"] == 4 else {"x": kw["player_id"]},
    )
    df, y = B.build("points", date(2026, 6, 1), date(2026, 6, 2))
    assert df.attrs["keys"] == [(1, date(2026, 6, 1)), (3, date(2026, 6, 2))]
    assert len(df) == len(y) == 2
