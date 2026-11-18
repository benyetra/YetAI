"""Prop generators serve the feature version the loaded model declares, and flag short samples."""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.predictions_models import (
    AssistsProjections,
    PlayerInjuryStatus,
    PointsProjections,
    ReboundsProjections,
    ThreePointProjections,
)
from app.services.etl.nba import _feature_engineering as fe
from app.services.etl.nba import _ml_predict as mlp
from app.services.etl.nba import (
    generate_assists_predictions,
    generate_points_predictions,
    generate_rebounds_predictions,
    generate_three_pt_made_predictions,
)
from tests.fake_s3 import Static
from tests.test_nba_prop_features_v4 import (
    OPP,
    OWN,
    P,
    STAR,
    TARGET,
    new_db,
    row,
    season,
    tonight,
)

MODELS = [
    PointsProjections,
    ReboundsProjections,
    AssistsProjections,
    ThreePointProjections,
]
NEWBIE = 7  # 2 current-season games plus last season


class StubModel:
    """predict = 20 + 10 * team_out_min_share per row; remembers the columns it saw."""

    def __init__(self):
        self.columns: list[str] = []

    def predict(self, X):
        self.columns = list(X.columns)
        share = (
            X["team_out_min_share"] if "team_out_min_share" in X else 0 * X.iloc[:, 0]
        )
        return (20 + 10 * share).to_numpy()


def make_db():
    db = new_db()
    for m in MODELS:
        m.__table__.create(db.get_bind())
    return db


def install(monkeypatch, stat, db, *, declares_v4):
    """Stub model whose metadata lists the feature names of the declared version."""
    names = list(
        fe.build_features(db, P, TARGET, OPP, stat, version=4 if declares_v4 else 3)
    )
    meta = {"features": names, "model_version": "xgb-test"}
    if declares_v4:
        meta["features_version"] = 4
    stub = StubModel()
    monkeypatch.setattr(mlp, "_OBJECTS", {stat: (Static(stub), Static(meta))})
    return stub


def run_generator(monkeypatch, mod, db):
    def fake_fanduel(row_, **kw):
        row_.fanduel_line = 20.0
        row_.fanduel_over_under = "OVER"
        return True

    monkeypatch.setattr(mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(
        mod, "now_eastern", lambda: SimpleNamespace(date=lambda: TARGET)
    )
    monkeypatch.setattr(mod, "apply_fanduel_to_projection", fake_fanduel)
    monkeypatch.setattr(mod, "resolve_nba_prop_model_version", lambda *a, **k: "x")
    monkeypatch.setattr(mod, "line_diagnostics", lambda: {}, raising=False)
    monkeypatch.setattr(mod, "maybe_attach_p_over", lambda *a, **k: None, raising=False)
    monkeypatch.setenv("NBA_LAST10_PROPS", "0")
    return mod.run()


def proj(db, model, pid):
    return db.query(model).filter(model.player_id == pid).one()


CASES = [
    (generate_points_predictions, PointsProjections, "points", "projected_points"),
    (
        generate_rebounds_predictions,
        ReboundsProjections,
        "rebounds",
        "projected_rebounds",
    ),
    (generate_assists_predictions, AssistsProjections, "assists", "projected_assists"),
]


@pytest.mark.parametrize("mod,model,stat,col", CASES)
def test_v4_model_sees_a_star_going_out(monkeypatch, mod, model, stat, col):
    db = make_db()
    season(db)
    tonight(db)
    stub = install(monkeypatch, stat, db, declares_v4=True)
    run_generator(monkeypatch, mod, db)
    p1 = getattr(proj(db, model, P), col)
    assert "team_out_min_share" in stub.columns

    db.add(PlayerInjuryStatus(player_id=STAR, player_name="s", status="out"))
    db.commit()
    run_generator(monkeypatch, mod, db)
    assert getattr(proj(db, model, P), col) > p1
    assert proj(db, model, STAR).fanduel_over_under == "OUT"


def test_v3_model_gets_v3_features_and_ignores_the_star(monkeypatch):
    db = make_db()
    season(db)
    tonight(db)
    stub = install(monkeypatch, "points", db, declares_v4=False)
    mod = generate_points_predictions
    run_generator(monkeypatch, mod, db)
    p1 = proj(db, PointsProjections, P).projected_points
    assert "team_out_min_share" not in stub.columns
    assert stub.columns == list(
        fe.build_features(db, P, TARGET, OPP, "points", version=3)
    )

    db.add(PlayerInjuryStatus(player_id=STAR, player_name="s", status="out"))
    db.commit()
    run_generator(monkeypatch, mod, db)
    assert proj(db, PointsProjections, P).projected_points == p1
    assert proj(db, PointsProjections, STAR).fanduel_over_under == "OUT"


def test_low_sample_flags_short_current_season(monkeypatch):
    db = make_db()
    season(db)
    for i in range(12):  # last season
        db.add(row(NEWBIE, TARGET - timedelta(days=200 + i)))
    for i in (1, 2):  # this season
        db.add(row(NEWBIE, TARGET - timedelta(days=i * 3)))
    db.commit()
    tonight(db)
    from app.models.predictions_models import TodayActivePlayers

    db.add(
        TodayActivePlayers(
            player_id=NEWBIE,
            player_name="n",
            team_id=OWN,
            team_name="own",
            opponent_team_id=OPP,
            opponent_team_name="opp",
            game_date=TARGET,
            is_home_game=True,
        )
    )
    db.commit()
    install(monkeypatch, "points", db, declares_v4=True)
    run_generator(monkeypatch, generate_points_predictions, db)
    assert proj(db, PointsProjections, NEWBIE).low_sample is True
    assert proj(db, PointsProjections, P).low_sample is False


def test_last10_path_sets_low_sample(monkeypatch):
    db = make_db()
    season(db)
    tonight(db)
    mod = generate_three_pt_made_predictions
    monkeypatch.setattr(mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(
        mod, "now_eastern", lambda: SimpleNamespace(date=lambda: TARGET)
    )
    monkeypatch.setattr(mod, "apply_fanduel_to_projection", lambda *a, **k: False)
    monkeypatch.setattr(mod, "resolve_nba_prop_model_version", lambda *a, **k: "x")
    monkeypatch.setattr(mod._last10, "enabled", lambda stat: True)
    monkeypatch.setattr(mod._last10, "projection", lambda *a, **k: 2.0)
    monkeypatch.setattr(mod, "current_season_games", lambda *a: 2 if a[1] == P else 9)
    mod.run()
    assert proj(db, ThreePointProjections, P).low_sample is True
    assert proj(db, ThreePointProjections, STAR).low_sample is False


def test_migration_chain_and_import():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261118_nba_prop_low_sample.py"
    )
    spec = importlib.util.spec_from_file_location("low_sample_mig", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.revision == "20261118_nba_prop_low_sample"
    # Chained at integration: fair_price_shadow -> prop_best_fair_ev -> low_sample.
    assert mig.down_revision == "20261118_prop_best_fair_ev"
    assert len(mig.TABLES) == 5
