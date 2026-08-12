"""Tests for shared ``app.services.ml`` training package (no DB)."""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from app.services.etl.nba.ml_training.config import NBA_ML_CONFIG
from app.services.etl.wnba.ml_training.config import WNBA_ML_CONFIG
from app.services.ml import validate_model as shared_validate
from app.services.ml.config import LeagueMLConfig
from app.services.ml.train_model import train


@pytest.fixture
def small_dataset():
    rng = np.random.default_rng(1)
    n = 120
    feats = pd.DataFrame(
        {
            "points_l5": rng.normal(15, 5, n),
            "minutes_l5": rng.normal(28, 4, n),
            "season_points_avg": rng.normal(15, 5, n),
        }
    )
    target = pd.Series(0.8 * feats["points_l5"] + rng.normal(0, 2, n), name="points")
    return feats, target


def test_wnba_config_fields():
    assert WNBA_ML_CONFIG.table_prefix == "wnba"
    assert WNBA_ML_CONFIG.s3_prefix == "wnba/ml_models"
    assert WNBA_ML_CONFIG.supported_stats == (
        "points",
        "assists",
        "rebounds",
        "three_pt_made",
    )
    assert WNBA_ML_CONFIG.mae_gate["points"] == 4.5


def test_nba_config_fields():
    assert NBA_ML_CONFIG.table_prefix == "nba"
    assert NBA_ML_CONFIG.s3_prefix == "nba/ml_models"
    assert NBA_ML_CONFIG.supported_stats == ("points", "rebounds", "assists")
    assert NBA_ML_CONFIG.mae_gate == {
        "points": 5.0,
        "assists": 1.6,
        "rebounds": 2.2,
    }
    assert "nba._feature_engineering" in NBA_ML_CONFIG.feature_builder_path


def test_shared_validate_passes_wnba_gate(small_dataset):
    feats, target = small_dataset
    model, _ = train("points", feats, target)
    result = shared_validate.validate(WNBA_ML_CONFIG, "points", model, feats, target)
    assert result["gate_threshold"] == 4.5
    assert result["passes_gate"] is True


def test_shared_validate_fails_tight_gate(small_dataset):
    feats, target = small_dataset
    model, _ = train("points", feats, target)
    tight = LeagueMLConfig(
        table_prefix="test",
        s3_prefix="test/ml_models",
        feature_builder_path="test.build_features",
        feature_builder=lambda *a, **k: None,
        recent_games_model=object,
        mae_gate={"points": 0.01},
        supported_stats=("points",),
    )
    result = shared_validate.validate(tight, "points", model, feats, target)
    assert result["passes_gate"] is False


def test_shared_validate_unknown_stat_raises(small_dataset):
    feats, target = small_dataset
    model = xgb.XGBRegressor(n_estimators=5, max_depth=2, random_state=0)
    model.fit(feats, target)
    with pytest.raises(ValueError, match="no gate defined"):
        shared_validate.validate(WNBA_ML_CONFIG, "steals", model, feats, target)


def test_nba_validate_uses_nba_gates(small_dataset):
    feats, target = small_dataset
    model, _ = train("points", feats, target)
    result = shared_validate.validate(NBA_ML_CONFIG, "points", model, feats, target)
    assert result["gate_threshold"] == 5.0


def test_wnba_wrapper_mae_gate_patch_still_works(small_dataset):
    from app.services.etl.wnba.ml_training import validate_model as wnba_validate

    feats, target = small_dataset
    model, _ = train("points", feats, target)
    with patch.dict(wnba_validate.MAE_GATE, {"points": 0.01}):
        result = wnba_validate.validate("points", model, feats, target)
    assert result["passes_gate"] is False
