"""L6: calibration is fitted on the earlier holdout rows and gated on the later ones."""

from __future__ import annotations

import numpy as np

from app.services.etl.nba import prop_calibration as pc


def _drifting_holdout(n=200):
    """Same prediction spread in both halves, but the model over-predicts by +1
    early and under-predicts by 1 late: in aggregate it looks unbiased."""
    preds = np.tile(np.linspace(10, 30, n // 2), 2)
    bias = np.r_[np.ones(n // 2), -np.ones(n // 2)]
    return preds, preds - bias, np.round((preds - bias) * 2) / 2


def test_gate_is_judged_on_later_rows_not_the_fit_rows():
    preds, actuals, lines = _drifting_holdout()
    # What the old code did: fit and gate on the same rows -> looks fine.
    assert pc.fit_residual_calibration("points", preds, actuals, lines).passes_gate
    params, info = pc.fit_time_ordered("points", preds, actuals, lines)
    assert info["fit_rows"] + info["gate_rows"] == len(preds)
    assert info["fit_rows"] == len(preds) // 2
    # Fitted on the early half only (residual +1), not on all rows (0).
    assert abs(params.global_residual_mean - 1.0) < 1e-9
    # Late rows are off by -1 - (+1) after correction.
    assert abs(info["out_of_sample_max_bucket_residual"] - 2.0) < 1e-6
    assert params.passes_gate is False


def test_stable_model_passes_out_of_sample():
    rng = np.random.default_rng(1)
    preds = rng.uniform(10, 30, 400)
    actuals = preds + rng.normal(0, 0.2, 400)
    params, info = pc.fit_time_ordered(
        "points", preds, actuals, np.round(actuals * 2) / 2
    )
    assert params.passes_gate and info["gate_rows"] == 200


def test_too_few_rows_never_passes():
    params, info = pc.fit_time_ordered("points", [1.0, 2.0], [1.0, 2.0], [1.0, 2.0])
    assert params.passes_gate is False


def test_retrain_records_time_ordered_calibration(monkeypatch):
    import pandas as pd
    from datetime import date

    from app.services.etl.nba.ml_training import run_train_props

    rng = np.random.default_rng(0)
    n = 400
    feats = pd.DataFrame({"x": rng.normal(size=n), "y": rng.normal(size=n)})
    target = pd.Series(10 + 3 * feats["x"] + rng.normal(size=n))
    monkeypatch.setattr(
        "app.services.etl.nba.ml_training.run_train_props.build_training_dataset.build",
        lambda stat, start, end: (feats, target),
    )
    out = run_train_props.run(
        "points", season_start=date(2024, 10, 1), season_end=date(2025, 4, 30)
    )
    info = out["metadata"]["prop_calibration_eval"]
    assert info["method"] == "time_ordered"
    assert info["fit_rows"] + info["gate_rows"] == out["metadata"]["n_test"]
    assert out["metadata"]["prop_calibration"]["passes_gate"] == info["passes_gate"]
