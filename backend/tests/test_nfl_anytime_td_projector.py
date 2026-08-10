"""Tests for NFL anytime-TD projector (pure helpers + run with injected rows)."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

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


def test_project_prediction_from_features():
    out = project_prediction_from_features(_sample_feature_row())
    lam = 3.2 * 0.20 * 0.30 * 1.0 * 1.0 * 1.0
    assert abs(out["expected_tds"] - lam) < 1e-9
    assert 0.0 < out["td_probability"] < 1.0


def test_build_upsert_row_includes_metadata():
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


def test_run_without_rows_when_nflverse_unwired():
    with patch(
        "app.services.etl.nfl.anytime_td_projector._try_build_feature_rows",
        return_value=[],
    ):
        result = run(season=2025, week=5, feature_rows=None)

    assert result["status"] == "ok"
    assert result["predictions"] == 0
