"""L3: projection rows carry model_version; attach warns once; NBA by-version MAE."""

from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models.predictions_models import (
    NBASpreadProjections,
    PointsProjections,
    WNBAPointsProjections,
)
from app.services import ml_model_version as mv
from app.services import nba_accuracy_service as acc


def test_new_columns_exist():
    for model in (PointsProjections, NBASpreadProjections, WNBAPointsProjections):
        assert hasattr(model, "model_version")


def test_points_writer_stamps_manifest_version(monkeypatch):
    from app.services.etl.nba import generate_points_predictions as mod

    player = MagicMock(player_id=1, player_name="P", team_name="A")
    player.opponent_team_name = "B"
    player.opponent_team_id = 2
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [player]
    db.query.return_value.filter.return_value.first.return_value = None
    added = []
    db.add.side_effect = added.append
    monkeypatch.setattr(mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(mod, "build_points_features", lambda **k: {"x": 1})
    monkeypatch.setattr(mod, "predict_points", lambda f: 20.0)
    monkeypatch.setattr(mod, "apply_fanduel_to_projection", lambda *a, **k: False)
    monkeypatch.setattr(mod, "maybe_attach_p_over", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.services.etl.nba._ml_predict.get_model_version", lambda stat: "2026-11-13"
    )
    mod.run()
    assert [r.model_version for r in added] == ["2026-11-13"]


def test_nba_spread_row_version_ml_and_heuristic(monkeypatch):
    from app.services.etl.nba import spread_projector as nsp

    def run(ml: bool):
        db = MagicMock()
        game = MagicMock(
            game_date=date(2099, 5, 21),
            game_time=None,
            home_team_id=1,
            away_team_id=2,
            home_team_name="H",
            away_team_name="A",
            spread_home=-4.5,
            total=220.5,
        )
        db.query.return_value.order_by.return_value.all.return_value = []
        db.query.return_value.all.return_value = []
        db.query.return_value.filter.return_value.all.return_value = [game]
        monkeypatch.setattr(nsp, "SessionLocal", lambda: db)
        monkeypatch.setattr(nsp, "_load_elos", lambda d: {"H": 1500.0, "A": 1500.0})
        monkeypatch.setattr(nsp, "model_available", lambda: ml)
        monkeypatch.setattr(nsp, "build_game_features", lambda *a, **k: {"e": 1.0})
        monkeypatch.setattr(nsp, "predict_margin", lambda f: 7.5)
        monkeypatch.setattr(nsp, "get_model_version", lambda: "2026-11-13")
        with patch.object(nsp, "upsert_many") as um:
            nsp.run()
        return um.call_args[0][2][0]["model_version"]

    assert run(True) == "2026-11-13"
    assert run(False) == "elo-pace-v1"


def test_nba_totals_enrich_stamps_heuristic():
    from app.services.etl.nba import totals_ml

    proj = {"projected_total": 220.0, "factors": {}}
    with patch.object(totals_ml, "features_from_projection", return_value={}), patch.object(
        totals_ml, "predict_residual", return_value=None
    ):
        totals_ml.enrich_projection(proj)
    assert proj["model_version"] == "heuristic-v1"


def test_resolve_nba_prop_version_uses_loader(monkeypatch):
    monkeypatch.delenv("NBA_PROP_MODEL_VERSION", raising=False)
    monkeypatch.delenv("NBA_POINTS_MODEL_VERSION", raising=False)
    monkeypatch.setattr(
        "app.services.etl.nba._ml_predict.get_model_version", lambda stat: "m-123"
    )
    assert mv.resolve_nba_prop_model_version("points") == "m-123"


def test_attach_model_version_warns_once_per_class(caplog):
    class NoCol:
        pass

    mv._WARNED_MISSING.discard(NoCol)
    with caplog.at_level(logging.WARNING, logger=mv.logger.name):
        mv.attach_model_version(NoCol(), "v1")
        mv.attach_model_version(NoCol(), "v1")
    assert len([r for r in caplog.records if "NoCol" in r.getMessage()]) == 1
    row = SimpleNamespace(model_version=None)
    mv.attach_model_version(row, "v2")
    assert row.model_version == "v2"


def test_nba_accuracy_by_model_version():
    def col_row(**f):
        o = SimpleNamespace(**f)
        o.__table__ = SimpleNamespace(columns=[SimpleNamespace(name=k) for k in f])
        return o

    proj = {
        "PointsProjections": [
            col_row(
                id=1, player_id=1, date=date(2026, 5, 23), projected_points=18.0,
                fanduel_line=17.5, fanduel_over_under="over", model_version="v-a",
            ),
            col_row(
                id=2, player_id=2, date=date(2026, 5, 23), projected_points=10.0,
                fanduel_line=None, fanduel_over_under=None, model_version=None,
            ),
        ],
        "PointsActuals": [
            SimpleNamespace(
                player_id=1, date=date(2026, 5, 23), actual_points=20.0
            ),
            SimpleNamespace(
                player_id=2, date=date(2026, 5, 23), actual_points=14.0
            ),
        ],
    }
    db = MagicMock()

    def q(model):
        r = MagicMock()
        r.filter.return_value.all.return_value = proj.get(model.__name__, [])
        return r

    db.query.side_effect = q
    out = acc.daily_accuracy(db, target_date=date(2026, 5, 23))
    by = out["by_model_version"]["points_mae"]
    assert by["v-a"] == {"n": 1, "mae": 2.0}
    assert by["unknown"] == {"n": 1, "mae": 4.0}
