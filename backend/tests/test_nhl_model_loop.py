"""NHL model loop: S3 refresh (L1), heuristic kept in features_used (L9),
chronological holdout (L9), champion-gated upload (L2)."""

from __future__ import annotations

import json
import pickle

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyRegressor

from app.services.etl.nhl import goalie_saves_ml as gsm
from app.services.etl.nhl import player_shots_ml as psm
from app.services.etl.nhl import team_totals_ml as ttm
from app.services.etl.nhl.ml_training import train_goalie_model as tg
from app.services.etl.nhl.ml_training import train_player_shots_model as tp
from app.services.etl.nhl.ml_training import train_team_totals_model as tt
from app.services.ml import model_store
from tests.fake_s3 import FakeS3

# module, trainer module, train fn name, upload fn name, loaded-predict name, enrich fn
CASES = {
    "goalie": (gsm, tg, "train_goalie_model", "upload_goalie_model", "predict_saves_ml_loaded"),
    "shots": (psm, tp, "train_player_shots_model", "upload_player_shots_model", "predict_shots_ml_loaded"),
    "totals": (ttm, tt, "train_team_totals_model", "upload_team_totals_model", "predict_total_ml_loaded"),
}
IDS = list(CASES)


def _model(v: float) -> DummyRegressor:
    return DummyRegressor(strategy="constant", constant=v).fit([[0.0]], [v])


def _const(v: float) -> bytes:
    return pickle.dumps(_model(v))


def _meta(mod) -> bytes:
    return json.dumps({"features": mod.feature_names(), "model_version": "v"}).encode()


def _keys(mod):
    return f"{mod.S3_PREFIX}/{mod.MODEL_KEY}.pkl", f"{mod.S3_PREFIX}/{mod.MODEL_KEY}_metadata.json"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(model_store, "REFRESH_SECONDS", 0)
    for var in ("NHL_GOALIE_MODEL_LOCAL", "NHL_PLAYER_SOG_MODEL_LOCAL", "NHL_TOTALS_MODEL_LOCAL"):
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("name", IDS)
def test_loader_refreshes_and_recovers(name, monkeypatch):
    mod, _, _, _, loaded = CASES[name]
    pkl, meta = _keys(mod)
    s3 = FakeS3({pkl: _const(1.0), meta: _meta(mod)})
    monkeypatch.setattr(model_store.boto3, "client", lambda *_a, **_k: s3)
    feats = {n: 0.0 for n in mod.feature_names()}
    predict = getattr(mod, loaded)

    s3.fail_head = True  # S3 down on first use: must not stick
    assert predict(feats) is None
    s3.fail_head = False
    first = predict(feats)
    assert first is not None

    s3.put(pkl, _const(5.0), "e2")  # retrain lands while the worker is running
    assert predict(feats) != first

    s3.fail_head = True  # outage keeps last good model
    assert predict(feats) is not None


@pytest.mark.parametrize("name", IDS)
def test_trainer_split_is_chronological(name):
    mod, _, train_fn, _, _ = CASES[name]
    n = 100
    X = pd.DataFrame({c: np.arange(n, dtype=float) for c in mod.feature_names()})
    y = pd.Series(np.arange(n, dtype=float))
    _, meta = getattr(mod, train_fn)((X, y))
    assert meta["split"] == "chronological"
    # holdout is the last 20 rows, so its error is that of extrapolating past the train range
    assert meta["n_test"] == 20 and meta["holdout_mae"] > 5


def _enrich(name):
    if name == "goalie":
        return gsm.enrich_goalie_prediction_for_write(
            {"predicted_shots_against": 30.0, "predicted_save_pct": 0.9}, {}
        ), "heuristic_saves"
    if name == "shots":
        return psm.enrich_player_shots_prediction_for_write({"baseline_shots": 3.0}), "heuristic_shots"
    return ttm.enrich_team_totals_prediction_for_write({}), "heuristic_total"


@pytest.mark.parametrize("name", IDS)
@pytest.mark.parametrize("flag", ["", "1"])
def test_heuristic_always_in_features_used(name, flag, monkeypatch):
    mod, _, _, _, loaded = CASES[name]
    for var in ("NHL_GOALIE_ML_ENABLED", "NHL_PLAYER_SOG_ML_ENABLED", "NHL_TOTALS_ML_ENABLED"):
        monkeypatch.setenv(var, flag)
    monkeypatch.setattr(mod, loaded, lambda _f: 99.0)
    out, key = _enrich(name)
    fu = out["features_used"]
    assert fu[key] is not None and fu[key] != 99.0


@pytest.mark.parametrize("name", IDS)
def test_upload_is_champion_gated(name, monkeypatch):
    mod, trainer, _, upload, _ = CASES[name]
    pkl, meta = _keys(mod)
    s3 = FakeS3({pkl: _const(10.0), meta: _meta(mod)})
    monkeypatch.setattr(model_store.boto3, "client", lambda *_a, **_k: s3)
    X = pd.DataFrame({c: [0.0] * 10 for c in mod.feature_names()})
    y = pd.Series([1.0] * 10)  # live model (10.0) is far off; a 1.0 model is exact
    metadata = {"features": mod.feature_names(), "holdout_mae": 0.0}

    worse = getattr(trainer, upload)(_model(50.0), {**metadata, "holdout_mae": 49.0}, X, y)
    assert worse["status"] == "rejected_by_champion"
    assert s3.objects[pkl] == _const(10.0)

    better = getattr(trainer, upload)(_model(1.0), metadata, X, y)
    assert better["status"] == "uploaded"
    assert s3.objects[pkl] == _const(1.0)
