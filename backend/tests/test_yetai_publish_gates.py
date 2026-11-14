"""Publish gates: started games and ungradeable picks never reach subscribers (B3, B4, B16)."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api import admin_yetai_picks as picks
from app.models.bet_models import CreateParlayBetRequest, CreateYetAIBetRequest
from app.models.database_models import BetType
from app.services.yetai_bets_service_db import (
    YetAIBetsServiceDB,
    yetai_pick_ungradeable_reason as reason_for,
)
from app.tasks import expire_pending_picks as expire_task


def _iso(delta):
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _req(**kw):
    base = dict(
        sport="NBA",
        game="New York Knicks @ Boston Celtics",
        game_id="evt-1",
        home_team="Boston Celtics",
        away_team="New York Knicks",
        bet_type="spread",
        pick="Boston Celtics -4.5",
        odds="-110",
        confidence=80,
        reasoning="edge",
        game_time="x",
        commence_time=_iso(timedelta(hours=1)),
    )
    base.update(kw)
    return CreateYetAIBetRequest(**base)


def _create(req):
    with patch("app.services.yetai_bets_service_db.SessionLocal") as sl:
        db = MagicMock()
        sl.return_value = db
        res = asyncio.run(YetAIBetsServiceDB().create_bet(req, admin_user_id=1))
    return res, db


def _bet(sport="NBA", bt=BetType.SPREAD, sel="Boston Celtics -4.5", ct=None, **kw):
    return SimpleNamespace(
        sport=sport,
        bet_type=bt,
        selection=sel,
        title="g",
        home_team="Boston Celtics",
        away_team="New York Knicks",
        commence_time=ct,
        created_at=datetime.utcnow(),
        prediction_factors={},
        **kw,
    )


def test_started_game_refused_future_ok():
    res, db = _create(_req(commence_time=_iso(timedelta(minutes=-5))))
    assert res["success"] is False and "already started" in res["error"]
    db.add.assert_not_called()
    res, _ = _create(_req(commence_time=_iso(timedelta(minutes=10))))
    assert res["success"] is False  # inside the 20 minute buffer
    res, db = _create(_req())
    assert res["success"] is True


def test_kill_switch_allows_started_game(monkeypatch):
    monkeypatch.setenv("YETAI_PUBLISH_GATES_ENABLED", "0")
    res, _ = _create(_req(commence_time=_iso(timedelta(minutes=-5))))
    assert res["success"] is True


@pytest.mark.parametrize(
    "kw",
    [
        dict(bet_type="moneyline", pick="BOS ML"),
        dict(sport="Tennis", bet_type="moneyline", pick="Moneyline Carlos Alcaraz"),
        dict(pick="Celtics -4.5 (1H)"),
    ],
)
def test_ungradeable_create_refused(kw):
    res, db = _create(_req(**kw))
    assert res["success"] is False and res["error"]
    db.add.assert_not_called()


def test_gradeable_examples_have_no_reason():
    assert reason_for(_bet()) is None
    assert reason_for(_bet(bt=BetType.TOTAL, sel="Over 220.5")) is None
    assert (
        reason_for(_bet(bt=BetType.PROP, sel="Jayson Tatum over 27.5 Points")) is None
    )
    mlb = _bet(sport="MLB", sel="New York Yankees -1.5")
    mlb.home_team, mlb.away_team = "New York Yankees", "Boston Red Sox"
    assert reason_for(mlb) is None
    assert "1h" in reason_for(_bet(sel="Celtics -4.5 (1H)")).lower()
    assert "Tennis" in reason_for(_bet(sport="Tennis", bt=BetType.MONEYLINE, sel="X"))


def test_run_line_stored_as_spread():
    captured = {}
    with patch("app.services.yetai_bets_service_db.SessionLocal") as sl:
        db = MagicMock()
        sl.return_value = db
        db.add.side_effect = lambda o: captured.setdefault("bet", o)
        res = asyncio.run(
            YetAIBetsServiceDB().create_bet(
                _req(
                    sport="MLB",
                    bet_type="Run Line",
                    pick="New York Yankees -1.5",
                    home_team="New York Yankees",
                    away_team="Boston Red Sox",
                ),
                admin_user_id=1,
            )
        )
    assert res["success"] is True
    assert captured["bet"].bet_type == "spread"


def _leg(**kw):
    base = dict(
        sport="NBA",
        game="Knicks @ Celtics",
        game_id="e1",
        home_team="Boston Celtics",
        away_team="New York Knicks",
        bet_type="spread",
        pick="Boston Celtics -4.5",
        odds="-110",
        confidence=80,
        reasoning="r",
        game_time="x",
        commence_time=_iso(timedelta(hours=2)),
    )
    base.update(kw)
    return base


def _parlay(*legs):
    return CreateParlayBetRequest(
        name="p", legs=list(legs), total_odds="+264", confidence=80, reasoning="r"
    )


def _create_parlay(req):
    with patch("app.services.yetai_bets_service_db.SessionLocal") as sl:
        sl.return_value = MagicMock()
        return asyncio.run(YetAIBetsServiceDB().create_parlay(req, admin_user_id=1))


def test_parlay_started_leg_named():
    res = _create_parlay(
        _parlay(_leg(), _leg(game="Old Game", commence_time=_iso(timedelta(hours=-1))))
    )
    assert res["success"] is False
    assert "Leg 2" in res["error"] and "Old Game" in res["error"]
    assert _create_parlay(_parlay(_leg(), _leg()))["success"] is True


def test_parlay_ungradeable_leg_named():
    res = _create_parlay(_parlay(_leg(), _leg(pick="Boston Celtics -4.5 (1H)")))
    assert res["success"] is False and res["error"].startswith("Leg 2:")


def _pending(ct, **kw):
    return SimpleNamespace(
        id="p1",
        status="pending_approval",
        sport="NBA",
        bet_type=BetType.SPREAD,
        selection="Boston Celtics -4.5",
        title="g",
        home_team="Boston Celtics",
        away_team="New York Knicks",
        commence_time=ct,
        created_at=datetime.utcnow(),
        prediction_factors={},
        parlay_legs=None,
        **kw,
    )


def _db_with(*rows):
    db = MagicMock()
    q = db.query.return_value.filter.return_value
    q.first.return_value = rows[0]
    q.all.return_value = list(rows)
    return db


def _approve(bet):
    db = _db_with(bet)
    with patch.object(picks, "_serialize", lambda b: {"id": b.id}):
        return asyncio.run(picks.approve("p1", _={}, db=db)), db


def test_approve_started_400_future_active():
    bet = _pending(datetime.utcnow() - timedelta(minutes=5))
    with pytest.raises(HTTPException) as e:
        _approve(bet)
    assert e.value.status_code == 400 and "reject" in e.value.detail
    assert bet.status == "pending_approval"
    bet = _pending(datetime.utcnow() + timedelta(hours=2))
    _approve(bet)
    assert bet.status == "active"


def test_approve_ungradeable_400():
    bet = _pending(datetime.utcnow() + timedelta(hours=2))
    bet.selection = "Celtics -4.5 (1H)"
    with pytest.raises(HTTPException) as e:
        _approve(bet)
    assert e.value.status_code == 400


def test_approve_all_skips_started():
    ok = _pending(datetime.utcnow() + timedelta(hours=2))
    ok.id = "ok"
    late = _pending(datetime.utcnow() - timedelta(minutes=1))
    late.id = "late"
    out = asyncio.run(picks.approve_all(_={}, db=_db_with(ok, late)))
    assert out["approved"] == ["ok"]
    assert out["skipped"][0]["id"] == "late" and out["skipped"][0]["reason"]


def test_expiry_after_tipoff_service_and_task():
    row = _pending(datetime.utcnow() - timedelta(minutes=1))
    svc = YetAIBetsServiceDB()
    assert svc._expire_stale_pending_approval(_db_with(row)) == 1
    assert row.status == "rejected"

    row = _pending(datetime.utcnow() - timedelta(minutes=1))
    with patch.object(expire_task, "SessionLocal", return_value=_db_with(row)):
        assert expire_task.expire_pending_picks() == 1
    assert row.status == "rejected"
    fresh = _pending(datetime.utcnow() + timedelta(hours=1))
    assert svc._expire_stale_pending_approval(_db_with(fresh)) == 0
