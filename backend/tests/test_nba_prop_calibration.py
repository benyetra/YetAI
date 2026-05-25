"""Tests for NBA prop residual calibration (BKB-2.6)."""

from __future__ import annotations

import numpy as np

from app.services.etl.nba.prop_calibration import (
    RESIDUAL_MEAN_GATE,
    CalibrationBucket,
    CalibrationParams,
    attach_p_over,
    fit_residual_calibration,
    maybe_attach_p_over,
    p_over_line,
)


def _synthetic_holdout(
    n: int,
    *,
    bias: float = 0.0,
    noise: float = 0.5,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    actuals = rng.uniform(8.0, 28.0, size=n)
    preds = actuals + bias + rng.normal(0.0, noise, size=n)
    lines = np.round(actuals * 2) / 2
    return preds, actuals, lines


def test_fit_well_centered_passes_gate():
    preds, actuals, lines = _synthetic_holdout(500, bias=0.0, noise=0.4)
    params = fit_residual_calibration("points", preds, actuals, lines)
    assert params.passes_gate
    assert params.max_abs_bucket_residual_mean < RESIDUAL_MEAN_GATE
    assert len(params.buckets) >= 1


def test_fit_biased_fails_gate():
    preds, actuals, lines = _synthetic_holdout(500, bias=2.5, noise=0.2)
    params = fit_residual_calibration("points", preds, actuals, lines)
    assert not params.passes_gate
    assert params.max_abs_bucket_residual_mean >= RESIDUAL_MEAN_GATE


def test_p_over_line_high_when_projection_beats_line():
    preds, actuals, lines = _synthetic_holdout(400, bias=0.0, noise=0.35)
    params = fit_residual_calibration("rebounds", preds, actuals, lines)
    p_high = p_over_line(22.0, 15.5, params)
    p_low = p_over_line(10.0, 18.5, params)
    assert p_high > p_low
    assert 0.01 <= p_high <= 0.99


def test_p_over_respects_bucket_bias():
    params = CalibrationParams(
        stat="assists",
        passes_gate=True,
        method="normal",
        global_residual_mean=0.0,
        global_residual_std=1.0,
        max_abs_bucket_residual_mean=0.1,
        bucket_edges=[0.0, 50.0],
        buckets=[
            CalibrationBucket(
                lo=0.0,
                hi=50.0,
                count=100,
                residual_mean=-2.0,
                residual_std=1.0,
            )
        ],
    )
    # residual_mean negative => model under-predicts => E[actual] above projected
    assert p_over_line(10.0, 10.5, params) > 0.5


def test_calibration_params_roundtrip():
    preds, actuals, lines = _synthetic_holdout(200)
    params = fit_residual_calibration("points", preds, actuals, lines)
    restored = CalibrationParams.from_dict(params.to_dict())
    assert restored.stat == params.stat
    assert restored.passes_gate == params.passes_gate
    assert len(restored.buckets) == len(params.buckets)


def test_attach_p_over_factors_column():
    class Row:
        factors = None

    row = Row()
    attach_p_over(row, 0.62)
    assert row.factors == {"p_over": 0.62}


def test_maybe_attach_p_over_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NBA_PROP_CALIBRATION_ENABLED", raising=False)

    class Row:
        fanduel_line = 20.5
        factors = None

    row = Row()
    assert maybe_attach_p_over(row, stat="points", projected=24.0, line=20.5) is None
    assert row.factors is None
