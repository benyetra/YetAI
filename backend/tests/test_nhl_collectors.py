"""NHL actuals collectors against an in-memory DB: name forms, id joins, upserts, lookback."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.predictions_models import (
    NHLGoalieActuals,
    NHLGoaliePredictions,
    NHLPlayerShotsActuals,
    NHLPlayerShotsPredictions,
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
)
from app.services import nhl_accuracy_service as svc
from app.services.etl.nhl import _boxscore as bx
from app.services.etl.nhl import collect_goalie_actuals as goalies
from app.services.etl.nhl import collect_team_totals_actuals as totals

FIX = Path(__file__).parent / "fixtures/nhl"
BOX = json.loads((FIX / "nhl_boxscore_2026020286.json").read_text())
SCHED = json.loads((FIX / "nhl_schedule_2026-11-10.json").read_text())
GAME_ID, DAY = 2026020286, date(2026, 11, 10)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            m.__table__
            for m in (
                NHLGoalieActuals,
                NHLGoaliePredictions,
                NHLPlayerShotsActuals,
                NHLPlayerShotsPredictions,
                NHLTeamTotalsActuals,
                NHLTeamTotalsPredictions,
            )
        ],
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _writer_totals_prediction(rec="OVER 5.5", line=5.5) -> NHLTeamTotalsPredictions:
    """A prediction row exactly as daily_predictions.generate_team_totals_predictions
    stores it: placeName names and ids from the schedule game's team objects."""
    game = next(g for d in SCHED["gameWeek"] for g in d["games"] if g["id"] == GAME_ID)
    return NHLTeamTotalsPredictions(
        game_date=DAY,
        home_team_id=game["homeTeam"]["id"],
        home_team_name=game["homeTeam"]["placeName"]["default"],
        away_team_id=game["awayTeam"]["id"],
        away_team_name=game["awayTeam"]["placeName"]["default"],
        predicted_home_goals=3.0,
        predicted_away_goals=3.0,
        predicted_total_goals=6.0,
        suggested_ou_line=6.0,
        draftkings_ou_line=line,
        betting_recommendation=rec,
    )


def _collect_totals(db):
    row = bx.extract_team_totals(BOX, game_id=GAME_ID, game_date=DAY)
    return totals._persist_row(db, row)


def test_prediction_as_writer_stores_it_joins_to_actual_as_collector_stores_it(db):
    pred = _writer_totals_prediction()  # 9 goals vs 5.5 → over
    db.add(pred)
    db.commit()
    assert _collect_totals(db) == "inserted"
    db.commit()

    actual = db.query(NHLTeamTotalsActuals).one()
    # same name form on both sides, and the prediction mirror was found
    assert (actual.home_team_name, actual.away_team_name) == (
        pred.home_team_name,
        pred.away_team_name,
    )
    assert actual.predicted_total_goals == 6.0 and actual.recommendation_correct is True

    rows = svc._nhl_rows(db, start=DAY, end=DAY)["team_totals"]
    assert rows[0]["actual_total_goals"] == 9
    out = svc.past_row_results(db, target_date=DAY)["team_totals"]
    assert out[pred.id]["result"] == "hit"


def test_totals_recollect_heals_blank_names_and_is_idempotent(db):
    db.add(_writer_totals_prediction())
    # a row as the old collector stored it: blank names, no mirror
    db.add(
        NHLTeamTotalsActuals(
            game_id=GAME_ID,
            game_date=DAY,
            home_team_id=10,
            home_team_name="",
            away_team_id=21,
            away_team_name="",
            actual_home_goals=3,
            actual_away_goals=6,
            actual_total_goals=9,
        )
    )
    db.commit()
    assert _collect_totals(db) == "updated"
    db.commit()
    actual = db.query(NHLTeamTotalsActuals).one()
    assert actual.home_team_name == "Toronto" and actual.recommendation_correct is True
    assert _collect_totals(db) == "unchanged"
    assert db.query(NHLTeamTotalsActuals).count() == 1


def _goalie_prediction(**kw) -> NHLGoaliePredictions:
    base = dict(
        game_date=DAY,
        game_id=GAME_ID,
        goalie_id=8478406,  # M. Blackwood in the fixture: 28 saves
        goalie_name="Mackenzie Blackwood",  # full name, as the projection writer stores it
        team_id=21,
        team_name="Colorado",
        opponent_team_id=10,
        opponent_team_name="Toronto",
        predicted_saves=27.0,
        predicted_shots_against=29.0,
        predicted_save_pct=0.9,
        saves_line=27.5,
        betting_recommendation="OVER 27.5",
    )
    base.update(kw)
    return NHLGoaliePredictions(**base)


def _collect_goalies(db, monkeypatch):
    monkeypatch.setattr(goalies, "db_session", db)
    stats = goalies.extract_goalie_stats(BOX, GAME_ID, DAY)
    return goalies.match_with_predictions(
        [s for s in stats if s["goalie_id"] == 8478406]
    )


def test_goalie_actual_matches_prediction_by_id_not_name(db, monkeypatch):
    db.add(_goalie_prediction())
    db.commit()
    assert _collect_goalies(db, monkeypatch)["inserted"] == 1
    a = db.query(NHLGoalieActuals).one()
    assert a.goalie_name == "M. Blackwood"  # boxscore spelling differs from prediction
    assert a.team_name == "Colorado"  # not blank
    assert a.predicted_saves == 27.0 and a.saves_line == 27.5
    assert a.recommendation_correct is True  # 28 saves > 27.5


def test_goalie_push_is_not_a_loss(db, monkeypatch):
    db.add(_goalie_prediction(saves_line=28.0, betting_recommendation="OVER 28.0"))
    db.commit()
    _collect_goalies(db, monkeypatch)
    assert db.query(NHLGoalieActuals).one().recommendation_correct is None


def test_goalie_without_prediction_does_not_crash_and_recollect_is_idempotent(
    db, monkeypatch
):
    assert _collect_goalies(db, monkeypatch)["inserted"] == 1  # no prediction at all
    db.add(_goalie_prediction())
    db.commit()
    assert _collect_goalies(db, monkeypatch)["updated"] == 1  # mirror filled in
    assert _collect_goalies(db, monkeypatch)["unchanged"] == 1
    assert db.query(NHLGoalieActuals).count() == 1


def test_schedule_only_takes_games_from_the_target_day(monkeypatch):
    resp = SimpleNamespace(
        status_code=200, raise_for_status=lambda: None, json=lambda: SCHED
    )
    monkeypatch.setattr(bx.requests, "get", lambda *a, **k: resp)
    days = {d["date"]: [g["id"] for g in d["games"]] for d in SCHED["gameWeek"]}
    got = bx.get_completed_games_for_date(date(2026, 11, 11))
    assert [g["id"] for g in got] == days["2026-11-11"]
    assert not {g["id"] for g in got} & set(days["2026-11-10"])


def test_collectors_regrade_the_shared_lookback_window(monkeypatch):
    from app.services.etl import grading_window

    monkeypatch.setattr(grading_window, "eastern_today", lambda: date(2026, 11, 13))
    monkeypatch.delenv("NHL_GRADING_LOOKBACK_DAYS", raising=False)
    seen = []

    def fake(d):
        seen.append(d)
        return {
            "date": d.isoformat(),
            "games_processed": 1,
            "rows_inserted": 0,
            "rows_updated": 1,
        }

    out = bx.run_for_grading_dates(fake, "t")
    assert seen == [date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)]
    assert out["rows_updated"] == 3 and out["dates"][-1] == "2026-11-12"


def test_team_shots_collector_not_in_nhl_phases():
    from app.tasks import etl_pipeline

    tasks = [t for _name, ts in etl_pipeline.NHL_PHASES for t in ts]
    assert etl_pipeline.nhl_collect_team_shots_actuals not in tasks
    assert etl_pipeline.nhl_collect_team_totals_actuals in tasks


def test_recollect_dry_run_writes_nothing_and_apply_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(totals, "init_session", lambda: db)
    monkeypatch.setattr(
        totals, "get_completed_games_for_date", lambda d: [{"id": GAME_ID}]
    )
    monkeypatch.setattr(totals, "get_game_boxscore", lambda gid: BOX)
    dry = totals.update_team_totals_actuals(DAY, commit=False)
    assert dry["rows_inserted"] == 1
    assert db.query(NHLTeamTotalsActuals).count() == 0
    assert totals.update_team_totals_actuals(DAY)["rows_inserted"] == 1
    again = totals.update_team_totals_actuals(DAY)
    assert (again["rows_inserted"], again["rows_updated"]) == (0, 0)
