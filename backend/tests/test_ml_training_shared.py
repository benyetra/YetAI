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


def test_build_releases_and_reconnects_on_dropped_connection(monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from sqlalchemy import column
    from sqlalchemy.exc import OperationalError

    from app.services.ml import build_training_dataset as btd

    rows = [
        SimpleNamespace(
            player_id=i, game_date=date(2025, 1, 1), opponent_team_id=1, points=i
        )
        for i in range(1, 6)
    ]
    sessions = []

    def make_session():
        s = MagicMock()
        s.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = (
            rows
        )
        sessions.append(s)
        return s

    calls = []

    def features(db, *, stat_col, player_id, game_date, opponent_team_id):
        calls.append((db, player_id))
        if player_id == 3 and db is sessions[0]:
            raise OperationalError("SELECT 1", {}, Exception("server closed"))
        return {"points_l5": float(player_id)}

    cfg = LeagueMLConfig(
        table_prefix="test",
        s3_prefix="test/ml_models",
        feature_builder_path="test.build_features",
        feature_builder=features,
        recent_games_model=SimpleNamespace(game_date=column("game_date")),
        mae_gate={"points": 5.0},
        supported_stats=("points",),
    )
    monkeypatch.setattr(btd, "SessionLocal", make_session)
    monkeypatch.setattr(btd, "RELEASE_EVERY", 2)

    feats, target = btd.build(cfg, "points", date(2025, 1, 1), date(2025, 1, 2))

    assert list(target) == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert len(sessions) == 2  # reconnected once
    assert (sessions[1], 3) in calls
    sessions[0].close.assert_called()
    assert sessions[1].rollback.call_count >= 1  # released at row 4


def test_parallel_build_keeps_date_order(monkeypatch):
    from datetime import date
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from sqlalchemy import column

    from app.services.ml import build_training_dataset as btd

    rows = [
        SimpleNamespace(
            player_id=i, game_date=date(2025, 1, 1), opponent_team_id=1, points=i
        )
        for i in range(1, 41)
    ]

    def make_session():
        s = MagicMock()
        s.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = (
            rows
        )
        return s

    def features(db, *, stat_col, player_id, game_date, opponent_team_id):
        return None if player_id % 7 == 0 else {"id": float(player_id)}

    cfg = LeagueMLConfig(
        table_prefix="test",
        s3_prefix="test/ml_models",
        feature_builder_path="test.build_features",
        feature_builder=features,
        recent_games_model=SimpleNamespace(game_date=column("game_date")),
        mae_gate={"points": 5.0},
        supported_stats=("points",),
    )
    monkeypatch.setattr(btd, "SessionLocal", make_session)
    monkeypatch.setattr(btd, "PARALLEL_MIN_ROWS", 10)
    monkeypatch.setattr(btd, "WORKERS", 3)

    feats, target = btd.build(cfg, "points", date(2025, 1, 1), date(2025, 1, 2))

    expected = [float(i) for i in range(1, 41) if i % 7]
    assert list(feats["id"]) == expected and list(target) == expected
