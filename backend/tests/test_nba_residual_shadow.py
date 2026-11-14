"""Residual shadow writer, review section and migration (SQLite)."""

import importlib.util
import pathlib
import re
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.models.predictions_models import (
    AssistsProjections,
    NBAGameLines,
    NBAPropShadow,
    ReboundsProjections,
    RecentGames,
    TodayActivePlayers,
)
from app.services import model_review_service as ms
from app.services.etl.nba.residual import dataset as ds
from app.services.etl.nba.residual import model as md
from app.services.etl.nba.residual import shadow
from tests.auto_pick.conftest import sqlite_db  # noqa: F401  (fixture)
from tests.test_nba_residual_dataset import H, A, START, _fixture

TODAY = (START + pd.Timedelta(days=30)).date()  # a fixture game date
LATER = datetime(2026, 1, 31, 23, 0)  # tip-off, naive UTC
BEFORE = datetime(2026, 1, 31, 12, 0)
AFTER = datetime(2026, 2, 1, 6, 0)
APP = pathlib.Path(__file__).resolve().parents[1] / "app"


@pytest.fixture
def slate(sqlite_db, monkeypatch):  # noqa: F811
    db = sqlite_db
    inputs = _fixture()
    inputs["lines"]["assists"] = 0
    both = inputs["lines"].copy()
    both["stat"] = "assists"
    inputs["lines"] = pd.concat([inputs["lines"], both], ignore_index=True)
    inputs["lines"]["over_price"] = -115.0
    inputs["lines"]["under_price"] = -105.0
    inputs["lines"]["best_over_price"] = -110.0
    inputs["lines"]["best_under_price"] = -100.0
    inputs["lines"]["price_side"] = "both"
    monkeypatch.setattr(ds, "load_inputs", lambda conn, s, e: inputs)
    train = {
        s: ds.build_rows(inputs, s, end=pd.Timestamp(TODAY) - pd.Timedelta(days=2))
        for s in shadow.STATS
    }
    models = {s: md.fit(train[s], ds.feature_columns(), "ridge", stat=s) for s in train}
    monkeypatch.setattr(shadow, "load_model", lambda stat: models.get(stat))
    db.add(
        NBAGameLines(
            game_date=TODAY, home_team_name="HH", away_team_name="AA", game_time=LATER
        )
    )
    for k in range(6):
        for pid, tn, on, tid, oid in (
            (1 + k, "HH", "AA", H, A),
            (11 + k, "AA", "HH", A, H),
        ):
            db.add(
                TodayActivePlayers(
                    player_id=pid,
                    player_name=f"P {pid}",
                    team_id=tid,
                    team_name=tn,
                    opponent_team_id=oid,
                    opponent_team_name=on,
                    game_date=TODAY,
                    is_home_game=tid == H,
                )
            )
        for model, col in (
            (ReboundsProjections, "projected_rebounds"),
            (AssistsProjections, "projected_assists"),
        ):
            db.add(
                model(
                    date=TODAY,
                    player_id=1 + k,
                    player_name=f"P {1 + k}",
                    opponent_team_name="AA",
                    fanduel_line=5.5,
                    fanduel_over_under="o",
                    fanduel_price=-120,
                    **{col: 6.1},
                )
            )
    db.commit()
    return db


def _snap(db):
    out = {}
    for m in (ReboundsProjections, AssistsProjections):
        cols = [c.name for c in m.__table__.columns]
        out[m.__tablename__] = [
            tuple(getattr(r, c) for c in cols) for r in db.query(m).order_by(m.id)
        ]
    return out


def test_projection_rows_byte_identical_and_shadow_has_line(slate):
    before = _snap(slate)
    res = shadow.run(TODAY, db=slate, now=BEFORE)
    assert _snap(slate) == before
    assert res["rebounds"]["written"] == 12 and res["assists"]["written"] == 12
    r = slate.query(NBAPropShadow).filter_by(stat="rebounds", player_id=1).one()
    assert r.line == 5.5 and r.over_price == -115 and r.best_over_price == -110
    assert r.line_source == "fanduel_projection" and r.model_version.startswith(
        "resid-"
    )
    assert r.features and r.date == TODAY


def test_started_game_not_written_rerun_updates(slate):
    res = shadow.run(TODAY, db=slate, now=AFTER)
    assert slate.query(NBAPropShadow).count() == 0
    assert res["rebounds"]["skipped_started"] == 12
    shadow.run(TODAY, db=slate, now=BEFORE)
    n = slate.query(NBAPropShadow).count()
    res = shadow.run(TODAY, db=slate, now=BEFORE)
    assert slate.query(NBAPropShadow).count() == n
    assert res["rebounds"]["updated"] == 12 and res["rebounds"]["written"] == 0


def test_no_model_and_disabled(slate, monkeypatch):
    monkeypatch.setattr(shadow, "load_model", lambda stat: None)
    res = shadow.run(TODAY, db=slate, now=BEFORE)
    assert res["rebounds"] == {"status": "no_model"}
    assert slate.query(NBAPropShadow).count() == 0
    monkeypatch.setenv("NBA_RESIDUAL_SHADOW_ENABLED", "0")
    assert shadow.run(TODAY, db=slate) == {"status": "disabled"}


def test_error_never_raises(slate, monkeypatch):
    def boom(conn, s, e):
        raise RuntimeError("x")

    monkeypatch.setattr(ds, "load_inputs", boom)
    res = shadow.run(TODAY, db=slate, now=BEFORE)
    assert res["status"] == "error" and res["rebounds"]["status"] == "error"


def test_auto_pick_does_not_touch_shadow():
    for f in (APP / "services" / "auto_pick").rglob("*.py"):
        src = f.read_text()
        assert not re.search(
            r"residual\.shadow|NBAPropShadow|pred_nba_prop_shadow", src
        ), f


# ---------------------------------------------------------------- review


def _shadow(
    db,
    d,
    pid,
    stat,
    resid,
    p_over,
    line=5.5,
    over_price=-120,
    under_price=-100,
    actual=None,
):
    db.add(
        NBAPropShadow(
            date=d,
            player_id=pid,
            player_name=f"P {pid}",
            stat=stat,
            line=line,
            over_price=over_price,
            under_price=under_price,
            pred_residual=resid,
            p_over=p_over,
            model_version="v",
        )
    )
    if actual is not None:
        db.add(
            RecentGames(
                player_id=pid,
                game_date=d,
                opponent_team_id=1,
                minutes=30.0,
                rebounds=actual,
                assists=actual,
            )
        )


def test_review_shadow_grading(sqlite_db):  # noqa: F811
    db = sqlite_db
    today = date(2026, 11, 14)
    y = today - timedelta(days=1)
    _shadow(db, y, 1, "rebounds", 1.0, 0.6, actual=8.0)  # over call, win at -120
    _shadow(db, y, 2, "rebounds", -1.0, 0.4, actual=8.0)  # under call, loss
    _shadow(db, y, 3, "rebounds", 0.2, 0.55, actual=3.0)  # below threshold, not a call
    _shadow(db, y, 4, "rebounds", 1.0, 0.6, actual=5.5)  # push: excluded
    _shadow(db, y, 5, "rebounds", 1.0, 0.6)  # no box row: ungraded
    _shadow(db, today, 6, "rebounds", 1.0, 0.6, actual=9.0)  # today: excluded
    db.commit()
    sec = ms._shadow_section(db, today)
    t = sec["stats"]["rebounds"]
    assert (t["calls"], t["hits"], t["graded"]) == (2, 1, 3)
    assert t["units_110"] == pytest.approx(0.91 - 1, abs=0.01)
    assert t["units_price"] == pytest.approx(100 / 120 - 1, abs=0.01)
    assert t["n_price"] == 2 and t["wilson95"][0] < 0.5 < t["wilson95"][1]
    bins = {b["bin"]: b for b in t["calibration"]}
    assert bins["0.6-0.7"]["n"] == 1 and bins["0.6-0.7"]["observed"] == 1.0
    assert t["brier_half"] == pytest.approx(0.25)
    assert "CLV pending: no snapshot table" in sec["clv"]["note"]
    text = ms.render_text({**_empty_review(today), "shadow": sec})
    assert "Residual shadow" in text and "1/2" in text and "CLV pending" in text


def _empty_review(today):
    gone = {"unavailable": "x"}
    keys = ("bets", "projections", "gate", "misses", "disagreements", "model_versions")
    return {
        "date": today.isoformat(),
        **dict.fromkeys(keys, gone),
        "clv": {"note": "n"},
    }


def test_review_no_rows_and_no_table():
    assert ms._shadow_section(_db_without_table(), date(2026, 11, 14)) == {
        "note": "no shadow rows"
    }


def _db_without_table():
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=create_engine("sqlite://"))()


def test_review_clv_with_snapshots(sqlite_db):  # noqa: F811
    from sqlalchemy import text

    db = sqlite_db
    today = date(2026, 11, 14)
    y = today - timedelta(days=1)
    _shadow(db, y, 1, "rebounds", 1.0, 0.6, actual=8.0)  # over call at 5.5
    _shadow(db, y, 2, "rebounds", -1.0, 0.4, actual=8.0)  # under call at 5.5
    db.commit()
    db.execute(
        text(
            "CREATE TABLE odds_line_snapshots (game_date DATE, market TEXT, player_key TEXT, "
            "book TEXT, line FLOAT, over_price INT, under_price INT, first_seen_at TIMESTAMP, "
            "commence_time TIMESTAMP)"
        )
    )
    rows = [  # (key, line, first_seen_at): later pre-start observation wins; post-start ignored
        ("p 1", 5.5, "2026-11-13 10:00"),
        ("p 1", 6.5, "2026-11-13 22:00"),
        ("p 1", 9.5, "2026-11-14 02:00"),
        ("p 2", 6.0, "2026-11-13 22:00"),
    ]
    for key, line, seen in rows:
        db.execute(
            text(
                "INSERT INTO odds_line_snapshots VALUES ('2026-11-13','player_rebounds',:k,'fanduel',"
                ":l,-110,-110,:s,'2026-11-14 00:00')"
            ),
            {"k": key, "l": line, "s": seen},
        )
    db.commit()
    clv = ms._shadow_section(db, today)["clv"]
    assert clv["n"] == 2 and clv["mean_move"] == pytest.approx((1.0 - 0.5) / 2)


# ---------------------------------------------------------------- migration


def _load_migration():
    path = next(
        (APP.parent / "alembic" / "versions").glob("20261114_nba_prop_shadow.py")
    )
    spec = importlib.util.spec_from_file_location("mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_creates_table_twice_and_downgrades():
    mig = _load_migration()
    assert mig.revision == "20261114_nba_prop_shadow" and len(mig.revision) <= 32
    assert mig.down_revision == "20261114_recent_games_game_id"
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
            mig.upgrade()
            cols = {c["name"] for c in inspect(conn).get_columns(mig.TABLE)}
            assert cols == {c.name for c in NBAPropShadow.__table__.columns}
            mig.downgrade()
            assert mig.TABLE not in inspect(conn).get_table_names()
