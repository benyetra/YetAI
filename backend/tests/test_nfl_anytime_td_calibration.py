"""Tests for anytime-TD GBM residual calibration (offline, no network)."""

from __future__ import annotations

from app.services.etl.nfl.anytime_td_model import (
    RB_TD_DISPERSION,
    anytime_td_probability,
)
from app.services.etl.nfl.anytime_td_calibration import (
    CALIBRATION_FEATURE_NAMES,
    apply_calibrated_probability,
    build_calibration_feature_vector,
    fit_residual_gbm,
    hierarchical_probability,
)


def test_hierarchical_probability_matches_model():
    p = hierarchical_probability(
        team_rz_trips=3.2,
        player_rz_share=0.2,
        conversion_rate=0.3,
        defense_mult=1.0,
        weather_mult=1.0,
        script_mult=1.0,
    )
    assert 0.0 < p < 1.0


def test_hierarchical_probability_rb_uses_negbin():
    kwargs = dict(
        team_rz_trips=3.2,
        player_rz_share=0.2,
        conversion_rate=0.3,
        defense_mult=1.0,
        weather_mult=1.0,
        script_mult=1.0,
    )
    pois = hierarchical_probability(**kwargs)
    rb = hierarchical_probability(**kwargs, position="RB")
    lam = 3.2 * 0.2 * 0.3
    assert abs(pois - anytime_td_probability(lam)) < 1e-12
    assert rb < pois
    assert abs(rb - anytime_td_probability(lam, dispersion=RB_TD_DISPERSION)) < 1e-12


def test_build_calibration_feature_vector_length():
    feats = build_calibration_feature_vector(
        {
            "position": "RB",
            "team_rz_trips": 3.5,
            "player_rz_share": 0.25,
            "conversion_rate": 0.35,
            "defense_mult": 1.1,
            "weather_mult": 1.0,
            "script_mult": 1.05,
            "snap_pct": 0.7,
            "rz_targets": 2.0,
            "gl_carries": 1.0,
            "expected_tds": 0.4,
            "td_probability": 0.33,
        }
    )
    assert len(feats) == len(CALIBRATION_FEATURE_NAMES)
    assert all(isinstance(x, float) for x in feats)


def test_build_calibration_feature_vector_rb_omitted_p_is_negbin():
    row = {
        "position": "RB",
        "team_rz_trips": 3.2,
        "player_rz_share": 0.2,
        "conversion_rate": 0.3,
        "defense_mult": 1.0,
        "weather_mult": 1.0,
        "script_mult": 1.0,
    }
    feats = build_calibration_feature_vector(row)
    hier_p = feats[CALIBRATION_FEATURE_NAMES.index("hier_p")]
    lam = 3.2 * 0.2 * 0.3
    assert (
        abs(hier_p - anytime_td_probability(lam, dispersion=RB_TD_DISPERSION)) < 1e-12
    )
    assert hier_p < anytime_td_probability(lam)


def test_residual_gbm_metadata_records_negbin_rb():
    from pathlib import Path
    import json

    meta_path = (
        Path(__file__).resolve().parents[1]
        / "models"
        / "nfl"
        / "anytime_td_residual_gbm.json"
    )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["hier_p_family"] == "poisson_except_rb_negbin"
    assert meta["rb_td_dispersion"] == RB_TD_DISPERSION
    assert "rb" in meta["groups"]


def test_fit_and_apply_residual_gbm_improves_or_stays_valid():
    # Synthetic: high hierarchical p should track positives after fit.
    rows = []
    for i in range(40):
        high = i % 2 == 0
        rows.append(
            {
                "position": "RB" if high else "WR",
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
        )
    model = fit_residual_gbm(rows, random_state=0, min_rows=20)
    assert model is not None
    p_high = apply_calibrated_probability(rows[0], model=model)
    p_low = apply_calibrated_probability(rows[1], model=model)
    assert 0.0 <= p_high <= 1.0
    assert 0.0 <= p_low <= 1.0
    assert p_high > p_low


def test_apply_without_model_returns_hierarchical():
    row = {
        "position": "TE",
        "team_rz_trips": 3.0,
        "player_rz_share": 0.2,
        "conversion_rate": 0.3,
        "defense_mult": 1.0,
        "weather_mult": 1.0,
        "script_mult": 1.0,
        "expected_tds": 0.18,
        "td_probability": 0.1647,
    }
    assert apply_calibrated_probability(row, model=None) == row["td_probability"]
