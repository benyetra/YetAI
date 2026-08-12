"""Tests for WNBA prop residual calibration (NBA parity)."""

from __future__ import annotations

import numpy as np

from app.services.etl.wnba.prop_calibration import (
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


def test_p_over_line_high_when_projection_beats_line():
    preds, actuals, lines = _synthetic_holdout(400, bias=0.0, noise=0.35)
    params = fit_residual_calibration("rebounds", preds, actuals, lines)
    assert p_over_line(22.0, 15.5, params) > p_over_line(10.0, 18.5, params)


def test_attach_p_over_on_dict_row():
    row: dict = {"market_line": 20.5}
    attach_p_over(row, 0.62)
    assert row["factors"]["p_over"] == 0.62


def test_maybe_attach_p_over_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WNBA_PROP_CALIBRATION_ENABLED", raising=False)
    row: dict = {"market_line": 20.5, "factors": None}
    assert maybe_attach_p_over(row, stat="points", projected=24.0, line=20.5) is None
    assert not row.get("factors")


def test_maybe_attach_p_over_when_enabled(monkeypatch):
    monkeypatch.setenv("WNBA_PROP_CALIBRATION_ENABLED", "1")
    params = CalibrationParams(
        stat="points",
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
                residual_mean=0.0,
                residual_std=1.0,
            )
        ],
    )
    monkeypatch.setattr(
        "app.services.etl.wnba.prop_calibration.load_calibration_params",
        lambda stat: params,
    )
    row: dict = {"market_line": 20.5}
    p = maybe_attach_p_over(row, stat="points", projected=24.0, line=20.5)
    assert p is not None and p > 0.5
    assert row["factors"]["p_over"] == round(p, 4)
