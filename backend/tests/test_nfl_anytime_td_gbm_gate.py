"""Regression: stale residual GBM must not invert RB vs TE anytime-TD boards."""

from __future__ import annotations

from app.services.etl.nfl.anytime_td_calibration import (
    CONVERSION_RATE_FAMILY_RZ_GL,
    MODEL_VERSION_HIER,
    apply_calibrated_probability,
    artifact_supports_current_lambda,
    calibrate_prediction_row,
    load_calibration_model,
    row_missing_form_for_calibration,
    should_apply_disk_calibration,
)
from app.services.etl.nfl.anytime_td_projector import project_prediction_from_features


def _gibbs_like(**overrides) -> dict:
    row = {
        "position": "RB",
        "team_rz_trips": 3.2,
        "player_rz_share": 0.28,
        "conversion_rate": 0.38,
        "defense_mult": 1.0,
        "weather_mult": 1.0,
        "script_mult": 1.15,
        "snap_pct": 0.55,
        # Week-1 thin: form fields absent (prod features null).
        "gl_carries": None,
        "rz_targets": None,
        "availability_mult": 1.0,
    }
    row.update(overrides)
    return row


def _hockenson_like(**overrides) -> dict:
    row = {
        "position": "TE",
        "team_rz_trips": 3.2,
        "player_rz_share": 0.14,
        "conversion_rate": 0.24,
        "defense_mult": 1.0,
        "weather_mult": 1.0,
        "script_mult": 1.0,
        "snap_pct": 0.55,
        "gl_carries": None,
        "rz_targets": None,
        "availability_mult": 1.0,
    }
    row.update(overrides)
    return row


def test_committed_artifact_is_not_rz_gl_compatible():
    meta = {
        "conversion_rate_family": "td_per_touch_pre_125",
        "model_version": "hierarchical_v1_gbm_pos",
    }
    assert not artifact_supports_current_lambda(meta)
    assert not artifact_supports_current_lambda(None)
    assert artifact_supports_current_lambda(
        {"conversion_rate_family": CONVERSION_RATE_FAMILY_RZ_GL}
    )


def test_thin_form_detection():
    assert row_missing_form_for_calibration(_gibbs_like())
    assert row_missing_form_for_calibration(_hockenson_like())
    assert not row_missing_form_for_calibration(_gibbs_like(gl_carries=1.5))
    assert not row_missing_form_for_calibration(_hockenson_like(rz_targets=1.2))


def test_stale_artifact_skips_gbm_even_when_env_on(monkeypatch):
    monkeypatch.setenv("NFL_ANYTIME_TD_GBM", "1")
    import app.services.etl.nfl.anytime_td_calibration as cal

    cal._MODEL = None
    cal._METADATA = None
    cal._LOAD_FAILED = False
    cal._INCOMPATIBLE_LOGGED = False
    cal._THIN_SKIP_LOGGED = False

    # Force-load committed artifact; metadata lacks rz_gl.
    load_calibration_model(force=True)
    assert not should_apply_disk_calibration(
        _gibbs_like(gl_carries=2.0, rz_targets=0.0)
    )


def test_stale_gbm_would_invert_rb_te_but_gate_preserves_hierarchy(monkeypatch):
    """Prod repro: Gibbs hier ~30% / Hock ~10%; raw GBM blend inverts them."""
    monkeypatch.setenv("NFL_ANYTIME_TD_GBM", "1")
    import app.services.etl.nfl.anytime_td_calibration as cal

    cal._MODEL = None
    cal._METADATA = None
    cal._LOAD_FAILED = False
    cal._INCOMPATIBLE_LOGGED = False
    cal._THIN_SKIP_LOGGED = False

    bundle = load_calibration_model(force=True)
    assert bundle is not None

    gibbs = _gibbs_like(gl_carries=0.0, rz_targets=0.0)
    hock = _hockenson_like(gl_carries=0.0, rz_targets=0.0)

    # Injected apply (bypass gate) still shows the OOD inversion.
    from app.services.etl.nfl.anytime_td_model import (
        RB_TD_DISPERSION,
        anytime_td_probability,
        expected_tds,
    )

    def _enrich(row: dict) -> dict:
        lam = expected_tds(
            team_rz_trips=row["team_rz_trips"],
            player_rz_share=row["player_rz_share"],
            conversion_rate=row["conversion_rate"],
            defense_mult=row["defense_mult"],
            weather_mult=row["weather_mult"],
            script_mult=row["script_mult"],
        )
        pos = row["position"]
        hier = anytime_td_probability(
            lam, dispersion=RB_TD_DISPERSION if pos == "RB" else None
        )
        out = dict(row)
        out["expected_tds"] = lam
        out["td_probability"] = hier
        return out

    g_en = _enrich(gibbs)
    h_en = _enrich(hock)
    g_raw = apply_calibrated_probability(g_en, model=bundle)
    h_raw = apply_calibrated_probability(h_en, model=bundle)
    assert g_en["td_probability"] > h_en["td_probability"]
    # Stale artifact with RZ conversion_rate crushes RB below TE.
    assert g_raw < h_raw

    # Projector / calibrate_prediction_row must keep hierarchical ranking.
    g_out = project_prediction_from_features(gibbs)
    h_out = project_prediction_from_features(hock)
    assert g_out["model_version"] == MODEL_VERSION_HIER
    assert h_out["model_version"] == MODEL_VERSION_HIER
    assert float(g_out["td_probability"]) > float(h_out["td_probability"])
    assert float(g_out["td_probability"]) > 0.25  # ~30% NegBin, not ~21% GBM crush
    assert float(h_out["td_probability"]) < 0.15  # ~10% Poisson, not ~25% TE cluster

    g_cal, g_gbm = calibrate_prediction_row(gibbs)
    h_cal, h_gbm = calibrate_prediction_row(hock)
    assert not g_gbm and not h_gbm
    assert g_cal > h_cal


def test_compatible_metadata_still_skips_thin_week1(monkeypatch):
    monkeypatch.setenv("NFL_ANYTIME_TD_GBM", "1")
    assert not should_apply_disk_calibration(
        _gibbs_like(),
        metadata={"conversion_rate_family": CONVERSION_RATE_FAMILY_RZ_GL},
    )
    assert should_apply_disk_calibration(
        _gibbs_like(gl_carries=1.2),
        metadata={"conversion_rate_family": CONVERSION_RATE_FAMILY_RZ_GL},
    )
