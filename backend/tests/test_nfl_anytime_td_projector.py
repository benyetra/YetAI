"""Tests for NFL anytime-TD projector (pure helpers + run with injected rows)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.nfl.anytime_td_model import (
    RB_TD_DISPERSION,
    anytime_td_probability,
)
from app.services.etl.nfl.anytime_td_projector import (
    ANYTIME_TD_UPSERT_UPDATE_KEYS,
    MODEL_VERSION,
    build_upsert_row,
    project_prediction_from_features,
    run,
)


def _sample_feature_row(**overrides) -> dict:
    row = {
        "player_id": "p1",
        "player_name": "Travis Kelce",
        "position": "TE",
        "team_name": "Kansas City Chiefs",
        "opponent_team_name": "Buffalo Bills",
        "season": 2025,
        "week": 5,
        "game_date": date(2025, 10, 5),
        "team_rz_trips": 3.2,
        "player_rz_share": 0.20,
        "conversion_rate": 0.30,
        "defense_mult": 1.0,
        "weather_mult": 1.0,
        "script_mult": 1.0,
        "snap_pct": 0.80,
    }
    row.update(overrides)
    return row


def test_project_prediction_from_features(monkeypatch):
    monkeypatch.setenv("NFL_ANYTIME_TD_GBM", "0")
    import app.services.etl.nfl.anytime_td_calibration as cal

    cal._MODEL = None
    cal._METADATA = None
    cal._LOAD_FAILED = False

    out = project_prediction_from_features(_sample_feature_row())
    lam = 3.2 * 0.20 * 0.30 * 1.0 * 1.0 * 1.0
    assert abs(out["expected_tds"] - lam) < 1e-9
    assert 0.0 < out["td_probability"] < 1.0
    assert out["model_version"] == MODEL_VERSION


def test_project_prediction_rb_probability_below_poisson(monkeypatch):
    monkeypatch.setenv("NFL_ANYTIME_TD_GBM", "0")
    import app.services.etl.nfl.anytime_td_calibration as cal

    cal._MODEL = None
    cal._METADATA = None
    cal._LOAD_FAILED = False

    out = project_prediction_from_features(_sample_feature_row(position="RB"))
    lam = float(out["expected_tds"])
    pois = anytime_td_probability(lam)
    nb = anytime_td_probability(lam, dispersion=RB_TD_DISPERSION)
    assert out["td_probability"] < pois
    assert abs(float(out["td_probability"]) - nb) < 1e-12


def test_project_prediction_scales_for_questionable(monkeypatch):
    monkeypatch.setenv("NFL_ANYTIME_TD_GBM", "0")
    import app.services.etl.nfl.anytime_td_calibration as cal

    cal._MODEL = None
    cal._METADATA = None
    cal._LOAD_FAILED = False

    base = project_prediction_from_features(_sample_feature_row())
    q = project_prediction_from_features(_sample_feature_row(availability_mult=0.75))
    assert q["expected_tds"] < base["expected_tds"]
    assert q["td_probability"] < base["td_probability"]


def test_build_upsert_row_includes_metadata(monkeypatch):
    monkeypatch.setenv("NFL_ANYTIME_TD_GBM", "0")
    # Clear any cached calibrator from other tests / local artifact.
    import app.services.etl.nfl.anytime_td_calibration as cal

    cal._MODEL = None
    cal._METADATA = None
    cal._LOAD_FAILED = False

    now = datetime(2025, 10, 1, 12, 0, 0)
    row = build_upsert_row(
        _sample_feature_row(),
        season=2025,
        week=5,
        now=now,
    )
    assert row["season"] == 2025
    assert row["week"] == 5
    assert row["player_id"] == "p1"
    assert row["game_date"] == date(2025, 10, 5)
    assert row["model_version"] == MODEL_VERSION
    assert row["prediction_date"] == now
    assert "features" in row
    assert row["expected_tds"] > 0
    assert row["td_probability"] > 0


def test_build_upsert_row_features_are_json_safe():
    """JSONB bind fails if features still contain Python date objects."""
    import json

    now = datetime(2025, 10, 1, 12, 0, 0)
    row = build_upsert_row(
        _sample_feature_row(game_date=date(2025, 10, 5)),
        season=2025,
        week=5,
        now=now,
    )
    assert row["features"]["game_date"] == "2025-10-05"
    # Must round-trip through stdlib json (same constraint as SQLAlchemy JSON).
    json.dumps(row["features"])


def test_run_with_injected_feature_rows_upserts():
    feature_rows = [_sample_feature_row()]
    mock_db = MagicMock()

    with (
        patch(
            "app.services.etl.nfl.anytime_td_projector.SessionLocal",
            return_value=mock_db,
        ),
        patch("app.services.etl.nfl.anytime_td_projector.upsert_many") as um,
    ):
        um.return_value = 1
        result = run(season=2025, week=5, feature_rows=feature_rows)

    assert result["status"] == "ok"
    assert result["predictions"] == 1
    um.assert_called_once()
    _, kwargs = um.call_args
    assert kwargs["update_keys"] == ANYTIME_TD_UPSERT_UPDATE_KEYS
    assert "created_at" not in kwargs["update_keys"]
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()


def test_run_without_rows_when_feature_build_empty():
    with patch(
        "app.services.etl.nfl.anytime_td_projector._try_build_feature_rows",
        return_value=[],
    ):
        result = run(season=2025, week=5, feature_rows=None)

    assert result["status"] == "ok"
    assert result["predictions"] == 0


def test_try_build_feature_rows_delegates_to_nflverse_builder():
    from app.services.etl.nfl.anytime_td_projector import _try_build_feature_rows

    sample = [
        {
            "player_id": "p1",
            "player_name": "A",
            "position": "RB",
            "team_name": "Kansas City Chiefs",
            "opponent_team_name": "Buffalo Bills",
            "team_rz_trips": 3.0,
            "player_rz_share": 0.2,
            "conversion_rate": 0.3,
            "defense_mult": 1.0,
            "weather_mult": 1.0,
            "script_mult": 1.0,
        }
    ]
    with patch(
        "app.services.etl.nfl.anytime_td_features.build_feature_rows_from_nflverse",
        return_value=sample,
    ) as builder:
        rows = _try_build_feature_rows(2025, 5)
    assert rows == sample
    builder.assert_called_once_with(2025, 5)
