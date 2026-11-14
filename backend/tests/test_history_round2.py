"""Round-2 history fixes: B1 scratched goalies, B2 MLB board, B3 NHL past rows, B4 degrade."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api.v1 import predictions as p
import app.models.database_models  # noqa: F401  (register tables)
from app.core.database import Base
from app.models.predictions_models import (
    NHLGoalieActuals,
    NHLGoaliePredictions,
)
from app.services import nhl_accuracy_service as svc
from app.services.etl.grading_window import eastern_today

PAST = eastern_today() - timedelta(days=2)


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _goalie(db, gid, d=PAST, **kw):
    base = dict(
        game_date=d,
        goalie_id=gid,
        goalie_name=f"Goalie {gid}",
        team_id=6,
        team_name="Boston",
        opponent_team_id=10,
        opponent_team_name="Toronto",
        is_home=True,
        was_scratch=False,
        predicted_saves=30.0,
        predicted_shots_against=32.0,
        predicted_save_pct=0.92,
        saves_line=26.5,
        betting_recommendation="OVER 26.5",
        confidence=70.0,
        prediction_date=datetime(2026, 1, 15, 12, 0),
    )
    base.update(kw)
    db.add(NHLGoaliePredictions(**base))
    db.commit()


def _actual(db, gid, saves, d=PAST):
    db.add(
        NHLGoalieActuals(
            game_id=gid,
            game_date=d,
            goalie_id=gid,
            goalie_name=f"Goalie {gid}",
            team_name="Boston",
            opponent_team_name="Toronto",
            actual_saves=saves,
            actual_shots_against=saves + 2,
            actual_save_pct=0.9,
            actual_goals_against=2,
        )
    )
    db.commit()


# ---- B1 ---------------------------------------------------------------------


def test_scratched_goalie_is_not_graded_but_stays_as_no_play(db):
    # Starter 1 scratched, played 9 relief saves; starter 2 replaced him.
    _goalie(db, 1, was_scratch=True)
    _goalie(db, 2)
    _actual(db, 1, 9)
    _actual(db, 2, 30)

    rows = svc._nhl_rows(db, start=PAST, end=PAST)["goalie"]
    assert len(rows) == 2  # the row is kept, not vanished
    scratched = next(r for r in rows if r["scratched"])
    assert scratched["betting_pick"] is None and scratched["actual_saves"] is None

    results = svc.past_row_results(db, target_date=PAST)["goalie_predictions"]
    assert sorted(v["result"] for v in results.values()) == ["hit", "no_play"]
    assert results[scratched["id"]]["scratched"] is True

    # tile / overview population: only the real starter is graded
    graded = svc.ou_call_graded_counts(
        [r for r in rows],
        line_field="saves_line",
        pick_field="betting_pick",
        actual_field="actual_saves",
    )
    assert graded == (1, 1)  # only the real starter's hit; no relief-saves miss


def test_board_marks_scratched_goalie_with_no_pick_or_tier(db):
    _goalie(db, 1, d=eastern_today(), was_scratch=True)
    _goalie(db, 2, d=eastern_today())
    out = p.nhl_predictions(
        target_date=eastern_today(),
        tz="UTC",
        limit=50,
        _user={"subscription_tier": "pro"},
        db=db,
    )
    by_gid = {r["goalie_id"]: r for r in out["goalie_predictions"]}
    s = by_gid[1]
    assert s["scratched"] is True
    assert not s.get("recommendation") and not s.get("betting_recommendation")
    assert not s.get("value_tier")
    assert not by_gid[2].get("scratched")
    assert by_gid[2]["betting_recommendation"] == "OVER 26.5"


# ---- B3 ---------------------------------------------------------------------


def test_nhl_past_view_returns_every_row_not_first_fifty(db):
    for i in range(1, 61):
        _goalie(db, i)
    out = p.nhl_predictions(
        target_date=PAST,
        tz="UTC",
        limit=50,
        _user={"subscription_tier": "pro"},
        db=db,
    )
    assert len(out["goalie_predictions"]) == 60
    live = p.nhl_predictions(
        target_date=eastern_today(),
        tz="UTC",
        limit=50,
        _user={"subscription_tier": "pro"},
        db=db,
    )
    assert live["goalie_predictions"] == []  # live path unchanged, other date


# ---- B4 ---------------------------------------------------------------------


@pytest.mark.parametrize("sport", ["nhl", "nba", "mlb", "wnba", "nfl"])
def test_merge_degrades_to_rows_without_results_and_logs(monkeypatch, caplog, sport):
    def boom(db, *, target_date):
        raise RuntimeError("grader exploded")

    mod = SimpleNamespace(past_row_results=boom)
    monkeypatch.setattr(p.importlib, "import_module", lambda name: mod)
    payload = {"goalie_predictions": [{"id": 1}]}
    db = MagicMock()
    with caplog.at_level(logging.ERROR):
        out = p._merge_past_results(payload, sport, db, PAST)
    assert out == {"goalie_predictions": [{"id": 1}]}
    assert "grader exploded" in caplog.text
    db.begin_nested.assert_called_once()  # savepoint, so a DB error can't poison the session


def test_db_error_in_grader_leaves_session_usable(db, monkeypatch):
    from sqlalchemy import text

    def boom(session, *, target_date):
        session.execute(text("select * from no_such_table"))

    monkeypatch.setattr(
        p.importlib,
        "import_module",
        lambda name: SimpleNamespace(past_row_results=boom),
    )
    out = p._merge_past_results({"x": [{"id": 1}]}, "nhl", db, PAST)
    assert out == {"x": [{"id": 1}]}
    assert db.execute(text("select 1")).scalar() == 1


# ---- B2 ---------------------------------------------------------------------


def _mlb(monkeypatch, db_pitchers, rows, target_date):
    calls = iter([rows, [], [], [], []])
    monkeypatch.setattr(p, "_query_recent", lambda *a, **k: next(calls))
    monkeypatch.setattr(p, "attach_news_to_rows", lambda db, rows, **k: rows)
    monkeypatch.setattr(p, "attach_mlb_batter_team_opponent", lambda db, rows: rows)
    monkeypatch.setattr(p, "attach_team_opponent_fields", lambda rows: rows)
    db = MagicMock()

    def query(model):
        q = MagicMock()
        q.all.return_value = db_pitchers if model.__name__ == "Pitcher" else []
        q.filter.return_value.all.return_value = []
        return q

    db.query.side_effect = query
    return p.mlb_predictions(
        target_date=target_date,
        tz="UTC",
        limit=50,
        total_line=None,
        _user={"subscription_tier": "pro"},
        db=db,
    )["strikeout_projections"]


def _k_row(pid):
    return {
        "id": int(pid),
        "pitcher_id": pid,
        "pitcher_name": f"P{pid}",
        "date": PAST,
        "fanduel_line": 5.5,
        "projected_strikeouts": 7.5,
    }


def test_mlb_live_board_omits_pitcher_not_on_slate(monkeypatch):
    meta = SimpleNamespace(
        pitcher_id="1",
        team="BOS",
        opponent="NYY",
        fanduel_point=5.5,
        fanduel_flag=None,
        prob_over=None,
        pick_edge_pct=None,
    )
    rows = _mlb(monkeypatch, [meta], [_k_row("1"), _k_row("2")], None)
    assert [r["pitcher_id"] for r in rows] == ["1"]


def test_mlb_past_board_keeps_pitcher_without_meta(monkeypatch):
    rows = _mlb(monkeypatch, [], [_k_row("2")], PAST)
    assert [r["pitcher_id"] for r in rows] == ["2"]
