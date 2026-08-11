"""Tests for position-specific anytime-TD GBM calibration groups."""

from __future__ import annotations

from app.services.etl.nfl.anytime_td_calibration import (
    calibration_group_for_position,
    fit_position_gbm_bundle,
    apply_calibrated_probability,
    model_for_row,
)


def _row(pos: str, high: bool) -> dict:
    return {
        "position": pos,
        "team_rz_trips": 4.0 if high else 2.0,
        "player_rz_share": 0.35 if high else 0.08,
        "conversion_rate": 0.4 if high else 0.2,
        "defense_mult": 1.0,
        "weather_mult": 1.0,
        "script_mult": 1.0,
        "snap_pct": 0.8 if high else 0.4,
        "rz_targets": 3.0 if high else 0.0,
        "gl_carries": 2.0 if high else 0.0,
        "expected_tds": 0.55 if high else 0.08,
        "td_probability": 0.42 if high else 0.08,
        "scored_anytime_td": high,
    }


def test_calibration_group_for_position():
    assert calibration_group_for_position("RB") == "rb"
    assert calibration_group_for_position("WR") == "pass"
    assert calibration_group_for_position("TE") == "pass"
    assert calibration_group_for_position("QB") == "qb"


def test_fit_position_gbm_bundle_and_apply():
    rows = []
    for i in range(50):
        high = i % 2 == 0
        rows.append(_row("RB", high))
    for i in range(50):
        high = i % 2 == 0
        rows.append(_row("WR" if i % 3 else "TE", high))
    for i in range(40):
        high = i % 2 == 0
        rows.append(_row("QB", high))

    bundle = fit_position_gbm_bundle(
        rows, random_state=0, min_rows={"rb": 20, "pass": 20, "qb": 20}
    )
    assert bundle is not None
    assert "rb" in bundle and "pass" in bundle
    # QB light may or may not fit depending on data; rb/pass required here.
    rb_high = apply_calibrated_probability(
        _row("RB", True), model=model_for_row(_row("RB", True), bundle)
    )
    rb_low = apply_calibrated_probability(
        _row("RB", False), model=model_for_row(_row("RB", False), bundle)
    )
    assert rb_high > rb_low
