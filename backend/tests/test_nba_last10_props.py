"""NBA-5: last-10 average for threes, steals, blocks, free throws."""

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import (
    Base,
    BlocksProjections,
    FreeThrowPredictions,
    PlayerInjuryStatus,
    RecentGames,
    StealsProjections,
    ThreePointProjections,
    TodayActivePlayers,
)
from app.services.etl.nba import (
    _last10,
    generate_blocks_predictions as gb,
    generate_free_throws_made_predictions as gft,
    generate_steals_predictions as gs,
    generate_three_pt_made_predictions as g3,
)

TODAY = date(2026, 11, 13)  # opener 2026-10-20
CUR = date(2026, 11, 1)
OLD = date(2026, 3, 1)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    tables = [
        m.__table__
        for m in (
            RecentGames,
            TodayActivePlayers,
            StealsProjections,
            ThreePointProjections,
            BlocksProjections,
            FreeThrowPredictions,
            PlayerInjuryStatus,
        )
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(session, "close", lambda: None)
    monkeypatch.delenv("NBA_LAST10_PROPS", raising=False)
    yield session
    session.close()


def _games(db, values, start, pid=1, stat="steals"):
    for i, v in enumerate(values):
        db.add(
            RecentGames(
                player_id=pid,
                game_date=start + timedelta(days=i),
                opponent_team_id=2,
                **{stat: v},
            )
        )
    db.commit()


def test_current_season_mean_when_five_or_more(db):
    _games(db, [9] * 5, OLD)
    _games(db, [1, 2, 3, 4, 5], CUR)
    assert _last10.projection(db, 1, TODAY, "steals") == 3.0


def test_falls_back_to_last_ten_across_seasons(db):
    _games(db, [10] * 6, OLD)
    _games(db, [0, 0, 0], CUR)
    # only 3 current-season rows: mean over all 9 rows
    assert _last10.projection(db, 1, TODAY, "steals") == pytest.approx(60 / 9)


def test_window_is_latest_ten(db):
    _games(db, [100] * 5, OLD)
    _games(db, [2] * 10, CUR)
    assert _last10.projection(db, 1, TODAY, "steals") == 2.0


def test_none_under_five_games(db):
    _games(db, [1, 2, 3, 4], CUR)
    assert _last10.projection(db, 1, TODAY, "steals") is None


def test_ignores_games_on_or_after_before(db):
    _games(db, [1] * 5, CUR)
    _games(db, [50], TODAY)
    _games(db, [50], TODAY + timedelta(days=1))
    assert _last10.projection(db, 1, TODAY, "steals") == 1.0


def test_ignores_null_stat(db):
    _games(db, [2] * 5, CUR)
    _games(db, [None] * 5, CUR + timedelta(days=10))
    assert _last10.projection(db, 1, TODAY, "steals") == 2.0


def test_enabled_switch(monkeypatch):
    monkeypatch.delenv("NBA_LAST10_PROPS", raising=False)
    assert _last10.enabled("steals")
    assert not _last10.enabled("points")
    for off in ("0", "false", "OFF"):
        monkeypatch.setenv("NBA_LAST10_PROPS", off)
        assert not _last10.enabled("steals")


GENS = [
    (gs, "steals", StealsProjections, "projected_steals"),
    (g3, "three_pt_made", ThreePointProjections, "projected_three_pt_made"),
    (gb, "blocks", BlocksProjections, "projected_blocks"),
    (gft, "free_throws_made", FreeThrowPredictions, "predicted_free_throws"),
]


def _wire(monkeypatch, db, mod):
    db.add(
        TodayActivePlayers(
            player_id=1,
            player_name="P1",
            team_id=1,
            team_name="A",
            opponent_team_id=2,
            opponent_team_name="B",
            game_date=TODAY,
        )
    )
    db.commit()
    monkeypatch.setattr(mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(mod, "now_eastern", lambda: _FakeNow())
    monkeypatch.setattr(mod, "active_players_not_started", lambda d, t: _active(d))
    if hasattr(mod, "get_event_id_for_game"):
        monkeypatch.setattr(mod, "get_event_id_for_game", lambda *a: None)


class _FakeNow:
    def date(self):
        return TODAY


def _active(db):
    return db.query(TodayActivePlayers).all()


@pytest.mark.parametrize("mod,stat,model,col", GENS)
def test_generator_writes_average_and_version_when_enabled(
    monkeypatch, db, mod, stat, model, col
):
    _games(db, [0.0] * 6, CUR, stat=stat)  # a 0.0 average is a valid projection
    _wire(monkeypatch, db, mod)

    def boom(*a, **k):
        raise AssertionError("model path used")

    monkeypatch.setattr(mod, "predict", boom)
    assert mod.run()["created"] == 1
    row = db.query(model).one()
    assert row.model_version == "last10-avg-v1"
    assert getattr(row, col) == 0.0


@pytest.mark.parametrize("mod,stat,model,col", GENS)
def test_generator_model_path_when_switched_off(monkeypatch, db, mod, stat, model, col):
    monkeypatch.setenv("NBA_LAST10_PROPS", "0")
    _wire(monkeypatch, db, mod)
    monkeypatch.setattr(mod, "build_features", lambda **k: {"f": 1})
    monkeypatch.setattr(mod, "predict", lambda s, f: 1.234)
    monkeypatch.setattr(mod, "resolve_nba_prop_model_version", lambda s: "xgb-v9")
    assert mod.run()["created"] == 1
    row = db.query(model).one()
    assert row.model_version == "xgb-v9"
    assert getattr(row, col) == 1.23
    # update path restamps too
    monkeypatch.setattr(mod, "resolve_nba_prop_model_version", lambda s: "xgb-v10")
    assert mod.run()["updated"] == 1
    assert db.query(model).one().model_version == "xgb-v10"
