"""NBA-10: actuals always equal the box score; regrade script counts then applies."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models.database_models  # noqa: F401  (register tables)
from app.core.database import Base
from app.models.predictions_models import (
    NBASpreadActuals,
    NBATotalsActuals,
    NBATotalsProjections,
    PointsActuals,
    PointsProjections,
    PRAActuals,
    PRAProjections,
    PredictionAccuracy,
    RecentGames,
)
from app.services.etl.nba import calculate_prediction_accuracy as cpa
from app.services.etl.nba import store_actuals as sa
from scripts import nba_regrade_actuals as regrade

D = date(2026, 10, 24)
D2 = date(2026, 10, 25)
HAWKS, CELTICS = 1610612737, 1610612738


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    cpa.db = session
    yield session
    session.close()
    engine.dispose()


def box(db, pid, d=D, opp=HAWKS, points=20.0, rebounds=5.0, assists=4.0):
    db.add(
        RecentGames(
            player_id=pid,
            game_date=d,
            opponent_team_id=opp,
            points=points,
            rebounds=rebounds,
            assists=assists,
        )
    )
    db.commit()


def proj(db, pid, d=D, opp="Atlanta Hawks"):
    db.add(
        PointsProjections(
            date=d,
            player_id=pid,
            player_name=f"P{pid}",
            opponent_team_name=opp,
            projected_points=18.0,
        )
    )
    db.add(
        PRAProjections(
            date=d,
            player_id=pid,
            player_name=f"P{pid}",
            opponent_team_name=opp,
            projected_points=18.0,
            projected_rebounds=5.0,
            projected_assists=4.0,
            projected_pra=27.0,
        )
    )
    db.commit()


def points_actual(db, pid, d=D, value=99.0):
    db.add(
        PointsActuals(date=d, player_id=pid, actual_points=value, projected_points=1)
    )
    db.add(
        PRAActuals(
            date=d,
            player_id=pid,
            player_name="x",
            opponent_team_name="x",
            actual_points=1,
            actual_rebounds=1,
            actual_assists=1,
            actual_pra=value,
            projected_pra=1,
        )
    )
    db.commit()


def actuals(db, model, d=D):
    return {a.player_id: a for a in db.query(model).filter_by(date=d)}


def store(db, d=D):
    sa.store_date(db, d)


def test_stale_actual_deleted_when_box_row_moved(db):
    proj(db, 1)
    box(db, 1, d=D2)  # box row re-dated away from D
    points_actual(db, 1)
    store(db)
    assert actuals(db, PointsActuals) == {}
    assert actuals(db, PRAActuals) == {}


def test_actual_value_corrected(db):
    proj(db, 1)
    box(db, 1, points=31.0)
    points_actual(db, 1, value=20.0)
    store(db)
    assert actuals(db, PointsActuals)[1].actual_points == 31.0
    assert actuals(db, PRAActuals)[1].actual_pra == 40.0


def test_opponent_mismatch_ends_ungraded(db):
    proj(db, 1, opp="Boston Celtics")  # box says Hawks
    box(db, 1, opp=HAWKS)
    points_actual(db, 1)
    store(db)
    assert actuals(db, PointsActuals) == {}
    assert actuals(db, PRAActuals) == {}


def test_opponent_case_insensitive_and_missing_name_not_blocked(db):
    proj(db, 1, opp="ATLANTA HAWKS")
    proj(db, 2, opp="")
    box(db, 1)
    box(db, 2)
    store(db)
    assert set(actuals(db, PointsActuals)) == {1, 2}


def test_orphan_actual_deleted_but_box_only_player_kept(db):
    points_actual(db, 7)  # no projection, no box row -> orphan
    points_actual(db, 8)  # no projection but has a box row -> untouched
    box(db, 8)
    store(db)
    assert set(actuals(db, PointsActuals)) == {8}


def test_pra_needs_all_three_stats(db):
    proj(db, 1)
    box(db, 1, assists=None)
    store(db)
    assert actuals(db, PointsActuals)[1].actual_points == 20.0
    assert actuals(db, PRAActuals) == {}


def test_accuracy_row_deleted_when_no_box_row(db):
    proj(db, 1)
    box(db, 1)
    cpa.calculate_accuracy_for_date(D)
    assert db.query(PredictionAccuracy).count() == 2  # points + pra
    db.query(RecentGames).delete()
    db.commit()
    result = cpa.calculate_accuracy_for_date(D)
    assert result["deleted"] == 2
    assert db.query(PredictionAccuracy).count() == 0


def test_accuracy_ignores_actuals_table_fallback(db):
    proj(db, 1)
    points_actual(db, 1)  # actuals row but no box row
    cpa.calculate_accuracy_for_date(D)
    assert db.query(PredictionAccuracy).count() == 0


def test_regrade_dry_run_counts_then_apply_then_zero(db):
    proj(db, 1)
    box(db, 1, points=31.0)  # value differs -> update
    points_actual(db, 1, value=20.0)
    proj(db, 2)  # box missing, stale actual -> delete
    points_actual(db, 2)
    proj(db, 3)  # no actual yet -> insert
    box(db, 3)
    db.add(
        NBASpreadActuals(
            game_date=D,
            home_team_name="Atlanta Hawks",
            away_team_name="Boston Celtics",
            home_score=100,
            away_score=90,
            actual_margin=10,
            home_won=True,
        )
    )
    db.add(
        NBATotalsProjections(
            game_date=D,
            home_team_name="Atlanta Hawks",
            away_team_name="Boston Celtics",
            projected_total=210.0,
            market_total=212.5,
        )
    )
    db.commit()

    before = regrade.count_changes(db, D, D)
    pts = before["stats"]["points"]
    assert (pts["updated"], pts["deleted"], pts["inserted"]) == (1, 1, 1)
    assert before["totals_to_fill"] == 1
    assert actuals(db, PointsActuals)[1].actual_points == 20.0  # dry run wrote nothing
    assert db.query(NBATotalsActuals).count() == 0

    regrade.apply_range(db, D, D)
    assert actuals(db, PointsActuals)[1].actual_points == 31.0
    assert set(actuals(db, PointsActuals)) == {1, 3}
    assert db.query(NBATotalsActuals).count() == 1
    assert regrade.total_changes(regrade.count_changes(db, D, D)) == 0
