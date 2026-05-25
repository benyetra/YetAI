"""Unit tests for shared model_version resolution (no network)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.services import ml_model_version as mv


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("xgb-2026-05-25", "xgb-2026-05-25"),
        ("  ensemble_v2  ", "ensemble_v2"),
        ("", "unknown"),
        ("a" * 30, "a" * 20),
    ],
)
def test_normalize_model_version(raw, expected):
    assert mv.normalize_model_version(raw, fallback="unknown") == expected


def test_model_version_from_metadata_priority():
    meta = {
        "model_version": "prod-2026",
        "training_run_id": "run-abc",
        "train_date": "2026-05-20",
    }
    assert mv.model_version_from_metadata(meta) == "prod-2026"


def test_model_version_from_metadata_mae_fallback():
    meta = {"holdout_mae": 1.23, "stat": "points"}
    assert mv.model_version_from_metadata(meta, prefix="xgb") == "xgb-mae1.2"


def test_resolve_strikeout_override():
    with patch.dict(os.environ, {"MLB_STRIKEOUT_MODEL_VERSION": "test-k-v1"}):
        assert (
            mv.resolve_mlb_strikeout_model_version(allow_network=False) == "test-k-v1"
        )


def test_resolve_strikeout_from_s3_metadata():
    meta = {"train_date": "2026-05-20"}
    with patch.object(mv, "fetch_s3_metadata_json", return_value=meta):
        assert (
            mv.resolve_mlb_strikeout_model_version(allow_network=False) == "2026-05-20"
        )


def test_resolve_strikeout_gb_with_local_mtime(tmp_path, monkeypatch):
    model_file = tmp_path / "strikeout_model.pkl"
    model_file.write_bytes(b"fake")
    with patch.object(mv, "fetch_s3_metadata_json", return_value=None):
        with patch(
            "app.services.etl.mlb.classification_model.MODEL_LOCAL_PATH",
            str(model_file),
        ):
            tag = mv.resolve_mlb_strikeout_model_version(allow_network=False)
    assert tag.startswith("gb-")


def test_resolve_game_heuristic_when_no_model():
    with patch("app.services.etl.mlb.game_model.load_model", return_value=None):
        assert (
            mv.resolve_mlb_game_projection_model_version(allow_network=False)
            == "heuristic-v1"
        )


def test_resolve_game_ensemble_feature_count():
    win = {"weights": {"xgboost": 0.4}, "feature_cols": ["a", "b", "c"]}
    with patch.object(mv, "fetch_s3_metadata_json", return_value=None):
        assert (
            mv.resolve_mlb_game_projection_model_version(
                win_model=win, allow_network=False
            )
            == "ens-3f"
        )


def test_attach_model_version_sets_column():
    row = MagicMock()
    row.model_version = None
    mv.attach_model_version(row, "heuristic-v1")
    assert row.model_version == "heuristic-v1"


def test_attach_model_version_no_column():
    row = object()
    mv.attach_model_version(row, "heuristic-v1")  # should not raise


def test_resolve_nba_prop_from_metadata():
    meta = {"model_version": "nba-pts-2026", "holdout_mae": 4.8}
    assert mv.resolve_nba_prop_model_version("points", metadata=meta) == "nba-pts-2026"


def test_resolve_nba_prop_override():
    with patch.dict(os.environ, {"NBA_PROP_MODEL_VERSION": "manual-v1"}):
        assert (
            mv.resolve_nba_prop_model_version("rebounds", metadata=None) == "manual-v1"
        )
