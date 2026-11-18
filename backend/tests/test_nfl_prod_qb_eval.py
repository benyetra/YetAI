"""Smoke tests for prod QB eval promote gate + ablation helpers."""

from __future__ import annotations

import json
import pickle
from datetime import date

import numpy as np
import pandas as pd

from app.services.etl.nfl.qb_passing_yards_ml import select_line_blend_weight
from scripts.nfl_prod_qb_eval import (
    _PROMOTE_LIFT,
    _line_pred_row,
    _mae,
    _market_baseline_row,
    promote_decision,
    run_holdout_ablations,
)


def test_promote_gate_is_ten_percent():
    assert _PROMOTE_LIFT == 0.10


def _gate(status="pass", reason=None):
    return {"passes": status == "pass", "status": status, "reason": reason}


def test_promote_decision_requires_tier_lift_and_passing_line_gate():
    ok, reason = promote_decision(ml_mae=54.0, tier_mae=65.0, gate=_gate())
    assert ok is True
    assert "NFL_QB_ML_ENABLED=1" in reason

    no_tier, _ = promote_decision(ml_mae=62.0, tier_mae=65.0, gate=_gate())
    assert no_tier is False

    for status in ("rejected_by_line_gate", "no_line_evidence"):
        ok, reason = promote_decision(
            ml_mae=54.0, tier_mae=65.0, gate=_gate(status, "x")
        )
        assert ok is False
        assert status in reason  # the recommendation names the gate status


def test_mae_helper():
    assert abs(_mae(np.array([10.0, 20.0]), np.array([12.0, 18.0])) - 2.0) < 1e-9


def test_select_line_blend_weight_prefers_better_mae():
    y = np.array([100.0, 200.0, 300.0])
    ml = np.array([140.0, 240.0, 340.0])
    line = np.array([100.0, 200.0, 300.0])
    real = np.array([True, True, True])
    sel = select_line_blend_weight(y_true=y, ml_pred=ml, line_pred=line, real_mask=real)
    # Diagnostic may pick pure line; promote wire-up excludes w=0.
    assert sel["diagnostic_best_w"] == 0.0
    assert sel["selected_w"] == 0.25
    assert sel["min_w_for_promote"] == 0.25


def test_market_and_line_baseline_helpers():
    feats = {
        "tier_yards": 250.0,
        "pass_yds_line": 270.0,
        "line_minus_tier": 20.0,
        "line_is_real": 1.0,
    }
    assert _market_baseline_row(feats, tier=250.0) == 260.0
    assert _line_pred_row(feats, tier=250.0, real_line=272.0) == 272.0
    assert _line_pred_row(feats, tier=250.0, real_line=None) == 270.0


def test_run_holdout_ablations_smoke():
    from app.services.etl.nfl.qb_features import FEATURE_NAMES

    n_train, n_test = 40, 20
    rng = np.random.default_rng(0)

    def _frame(n: int, season: int) -> pd.DataFrame:
        base = {name: np.zeros(n) for name in FEATURE_NAMES}
        base["tier_yards"] = np.linspace(200, 260, n)
        base["pass_yds_line"] = np.linspace(205, 265, n)
        base["line_minus_tier"] = base["pass_yds_line"] - base["tier_yards"]
        base["line_is_real"] = np.ones(n)
        base["season"] = np.full(n, season)
        base["week"] = np.arange(1, n + 1)
        base["rolling_yards_l3"] = base["tier_yards"] + rng.normal(0, 5, n)
        return pd.DataFrame(base)

    X_train = _frame(n_train, 2024)
    X_test = _frame(n_test, 2025)
    y_train = pd.Series(X_train["tier_yards"] + rng.normal(0, 8, n_train))
    y_test = (X_test["tier_yards"] + rng.normal(0, 8, n_test)).to_numpy()
    tier_test = X_test["tier_yards"].to_numpy()
    static_tier_test = tier_test.copy()
    meta_test = pd.DataFrame(
        {
            "pass_yds_line_real": X_test["pass_yds_line"].to_numpy(),
            "season": np.full(n_test, 2025),
            "week": np.arange(1, n_test + 1),
        }
    )
    out = run_holdout_ablations(
        X_train=X_train,
        y_train=y_train,
        X_test=X_test,
        y_test=y_test,
        meta_test=meta_test,
        tier_test=tier_test,
        static_tier_test=static_tier_test,
    )
    for key in (
        "dynamic_tier",
        "static_tier",
        "market_baseline_0_5_tier_line",
        "line_only",
        "v5_features_market_residual",
        "v6_features_market_residual",
        "market_residual_promote_sweep",
        "tier_only_residual",
        "tier_only_promote_sweep",
        "tier_only_residual_shallow",
        "tier_only_residual_strong_reg",
        "summary",
    ):
        assert key in out
    assert out["v6_features_market_residual"]["n_train"] == n_train
    assert out["v6_features_market_residual"]["fit_full"] is True
    assert out["market_residual_promote_sweep"]["fit_full"] is True
    assert out["market_residual_promote_sweep"]["baseline_mode"] == "market"
    assert out["tier_only_promote_sweep"]["baseline_mode"] == "tier"
    assert out["summary"].get("tier_only_lift_vs_dynamic_tier") is not None
    assert out["summary"].get("promote_path") == "market_residual_v6"
    assert out["summary"].get("promote_baseline_mode") == "market"


# ---- C6: weekly run learns from this season without leaking into the gate ----


class _Fit:
    """Picklable stand-in for a fitted model; remembers how many rows it saw."""

    def __init__(self, n):
        self.n = n


def _season_frames(n_old=60, n_new=45):
    from app.services.etl.nfl.qb_features import FEATURE_NAMES

    n = n_old + n_new
    f = {name: np.zeros(n) for name in FEATURE_NAMES}
    f["tier_yards"] = np.linspace(200, 260, n)
    features = pd.DataFrame(f)
    target = pd.Series(features["tier_yards"] + 3.0, name="actual_passing_yards")
    meta = pd.DataFrame(
        {
            "season": [2024] * n_old + [2025] * n_new,
            "week": list(range(1, n_old + 1)) + list(range(1, n_new + 1)),
            "tier_yards": features["tier_yards"],
            "static_tier_yards": features["tier_yards"],
            "pass_yds_line_real": [np.nan] * n,
            "pass_yds_line_source": ["none"] * n,
        }
    )
    return features, target, meta


def _run(monkeypatch, tmp_path, promote, frames=None, predict=None):
    import scripts.nfl_prod_qb_eval as ev
    import app.services.etl.nfl.qb_passing_yards_ml as qm

    fits = []

    def fake_train(dataset, **kw):
        fits.append(len(dataset[0]))
        return _Fit(len(dataset[0])), {"model_family": "x", "n_train": len(dataset[0])}

    monkeypatch.setattr(ev, "_build_with_meta", lambda a, b: frames or _season_frames())
    monkeypatch.setattr(ev, "_MODELS_DIR", tmp_path)
    monkeypatch.setattr(ev, "run_holdout_ablations", lambda **k: {})
    if promote is not None:
        monkeypatch.setattr(ev, "promote_decision", lambda **k: (promote, "r"))
    monkeypatch.setattr(qm, "train_promote_qb_yards_model", fake_train)
    monkeypatch.setattr(qm, "predict_yards_ml", predict or (lambda *a, **k: 250.0))
    report = ev.train_and_eval(
        season_start=date(2024, 9, 1), season_end=date(2025, 12, 1)
    )
    return report, fits


def test_shipped_model_is_refit_on_all_rows_after_the_gate_passes(
    monkeypatch, tmp_path
):
    report, fits = _run(monkeypatch, tmp_path, promote=True)
    assert fits[0] == 60  # gate fit: everything before the holdout season
    assert fits[-1] == 105  # shipped fit: all graded rows, incl. this season
    shipped = pickle.loads((tmp_path / "qb_passing_yards.pkl").read_bytes())
    assert shipped.n == 105
    assert report["rows_train"] == 60  # metrics stay on the honest holdout


def test_no_refit_when_the_gate_did_not_pass(monkeypatch, tmp_path):
    _, fits = _run(monkeypatch, tmp_path, promote=False)
    assert fits == [60]


def test_data_window_names_last_graded_week(monkeypatch, tmp_path):
    _run(monkeypatch, tmp_path, promote=True)
    meta = json.loads((tmp_path / "qb_passing_yards_metadata.json").read_text())
    assert meta["data_window"] == "2024w1..2025w45"


# ---- the line baseline is real lines only; --force-upload cannot waive the gate ----


def _real_vs_padded_frames(n_old=60, n_new=320):
    """Holdout: even rows have a real line (3 yds off the truth), odd rows have none."""
    features, target, meta = _season_frames(n_old, n_new)
    real = np.zeros(len(features), dtype=bool)
    real[n_old::2] = True
    features["line_is_real"] = real.astype(float)
    meta["pass_yds_line_real"] = np.where(real, target + 3.0, np.nan)
    return features, target, meta, real


def _ml_good_on_padded_bad_on_real(model, row, **k):
    # truth is tier + 3: exact where there is no line, 5 yards off where there is
    return row["tier_yards"] + 3.0 + (5.0 if row["line_is_real"] else 0.0)


def test_padded_rows_never_enter_the_line_baseline(monkeypatch, tmp_path):
    features, target, meta, real = _real_vs_padded_frames()
    report, _ = _run(
        monkeypatch,
        tmp_path,
        promote=False,
        frames=(features, target, meta),
        predict=_ml_good_on_padded_bad_on_real,
    )
    assert report["n_real_line_rows"] == 160
    assert report["line_mae"] == report["line_mae_real_rows"] == 3.0
    assert report["ml_mae_real_rows"] == 5.0
    assert report["line_mae_padded"] == 3.0  # tier fallback rows, diagnostic only
    assert report["mae_lift_vs_line"] < 0  # ML loses to the line on real rows


def test_beating_the_padded_baseline_but_losing_on_real_rows_is_not_promoted(
    monkeypatch, tmp_path
):
    features, target, meta, _ = _real_vs_padded_frames()
    report, fits = _run(
        monkeypatch,
        tmp_path,
        promote=None,  # the real promote_decision
        frames=(features, target, meta),
        predict=_ml_good_on_padded_bad_on_real,
    )
    assert report["mae_lift"] > 0.10  # clears the tier-lift bar ...
    assert report["promote_gate"]["status"] == "rejected_by_line_gate"
    assert report["promote_recommended"] is False  # ... but loses to the real line
    assert "rejected_by_line_gate" in report["recommendation"]
    assert fits == [60]  # no shipped refit


def test_no_real_lines_is_no_line_evidence_not_promoted(monkeypatch, tmp_path):
    report, _ = _run(monkeypatch, tmp_path, promote=None, predict=lambda *a, **k: 253.0)
    assert report["promote_gate"]["status"] == "no_line_evidence"
    assert report["line_mae"] is None and report["n_real_line_rows"] == 0
    assert report["promote_recommended"] is False


def _spy_upload(monkeypatch):
    import app.services.etl.nfl.ml_training.train_qb_model as tq

    calls = []
    monkeypatch.setattr(
        tq, "upload_local_artifacts", lambda *a: calls.append(a) or {"m": {}}
    )
    return calls


def test_force_upload_does_not_waive_a_failing_line_gate(monkeypatch):
    import scripts.nfl_prod_qb_eval as ev

    calls = _spy_upload(monkeypatch)
    report = {
        "promote_recommended": False,
        "promote_gate": _gate("rejected_by_line_gate", "worse_than_line"),
    }
    out = ev.maybe_upload(report, force=True)
    assert calls == []
    assert "line gate rejected_by_line_gate" in out["s3_upload_skipped"]
    assert out["force_upload"] is True


def test_force_upload_still_waives_the_tier_lift_when_the_gate_passes(monkeypatch):
    import scripts.nfl_prod_qb_eval as ev

    calls = _spy_upload(monkeypatch)
    ev.maybe_upload({"promote_recommended": False, "promote_gate": _gate()}, force=True)
    assert len(calls) == 1


def test_s3_upload_exception_exits_nonzero(monkeypatch, tmp_path, capsys):
    import sys

    import scripts.nfl_prod_qb_eval as ev

    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(sys, "argv", ["nfl_prod_qb_eval.py", "--upload"])
    monkeypatch.setattr(ev, "_MODELS_DIR", tmp_path)
    monkeypatch.setattr(ev, "train_and_eval", lambda **k: {"status": "ok"})

    def boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(ev, "maybe_upload", boom)
    assert ev.main() == 1
    assert "s3 down" in capsys.readouterr().out
