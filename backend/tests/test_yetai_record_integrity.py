"""Record integrity: delete only never-shown bets (B1), audited edits (B2), expired
auto picks (B12), ET game date (B15)."""

import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.api import admin_yetai_picks as picks
from app.models.database_models import (
    BetHistory,
    BetSource,
    BetType,
    SubscriptionTier,
    YetAIBet,
)
from app.services.yetai_bets_service_db import (
    YetAIBetsServiceDB,
    game_date_for_yetai_bet,
)

SERVICE = YetAIBetsServiceDB()


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):
    return "JSON"


ADMIN = {"id": 7}


@pytest.fixture
def Session():
    engine = create_engine("sqlite://")
    YetAIBet.__table__.create(engine)
    BetHistory.__table__.create(engine)
    return sessionmaker(bind=engine)


def _row(id="b1", status="active", ct=None, source=BetSource.MANUAL, **kw):
    base = dict(
        id=id,
        title="Knicks @ Celtics",
        description="d",
        bet_type=BetType.SPREAD,
        selection="Boston Celtics -4.5",
        odds=-110,
        confidence=80,
        sport="NBA",
        home_team="Boston Celtics",
        away_team="New York Knicks",
        status=status,
        source=source,
        commence_time=ct if ct is not None else datetime.utcnow() + timedelta(hours=5),
        prediction_factors={},
    )
    base.update(kw)
    return YetAIBet(**base)


def _delete(Session, bet_id):
    with patch("app.services.yetai_bets_service_db.SessionLocal", Session):
        return asyncio.run(SERVICE.delete_bet(bet_id, 1))


# ---------------------------------------------------------------- B1


@pytest.mark.parametrize("status", ["active", "pending", "won", "void", "lost"])
def test_delete_shown_bet_409_keeps_row_and_history(Session, status):
    db = Session()
    db.add(_row(status=status))
    db.add(BetHistory(bet_id="b1", user_id=1, action="placed"))
    db.commit()
    res = _delete(Session, "b1")
    assert res["success"] is False and res["code"] == 409
    assert "pull it instead" in res["error"]
    db = Session()
    assert db.query(YetAIBet).count() == 1
    assert db.query(BetHistory).count() == 1


@pytest.mark.parametrize("status", ["pending_approval", "rejected"])
def test_delete_never_shown_bet_removed(Session, status):
    db = Session()
    db.add(_row(status=status))
    db.commit()
    assert _delete(Session, "b1")["success"] is True
    assert Session().query(YetAIBet).count() == 0


def test_delete_route_returns_409():
    from app import main

    svc = MagicMock()

    async def fake(*a):
        return {"success": False, "code": 409, "error": "shown"}

    svc.delete_bet = fake
    with (
        patch.object(main, "is_service_available", return_value=True),
        patch.object(main, "get_service", return_value=svc),
    ):
        with pytest.raises(HTTPException) as e:
            asyncio.run(main.delete_yetai_bet("b1", admin_user=ADMIN))
    assert e.value.status_code == 409


# ---------------------------------------------------------------- B2


def _edit(db, payload, pick_id="b1"):
    return asyncio.run(picks.edit(pick_id, payload, _=ADMIN, db=db))


@pytest.mark.parametrize(
    "status", ["won", "lost", "pushed", "void", "expired", "rejected"]
)
def test_edit_terminal_409_unchanged(Session, status):
    db = Session()
    db.add(_row(status=status))
    db.commit()
    with pytest.raises(HTTPException) as e:
        _edit(db, picks.EditPickRequest(odds=-200))
    assert e.value.status_code == 409
    assert Session().get(YetAIBet, "b1").odds == -110


def test_edit_after_start_409(Session):
    db = Session()
    db.add(_row(ct=datetime.utcnow() - timedelta(minutes=5)))
    db.commit()
    with pytest.raises(HTTPException) as e:
        _edit(db, picks.EditPickRequest(odds=-200))
    assert e.value.status_code == 409
    assert Session().get(YetAIBet, "b1").odds == -110


def test_edit_odds_and_tier_audited(Session):
    db = Session()
    db.add(_row())
    db.commit()
    _edit(
        db,
        picks.EditPickRequest(odds=-125, tier_requirement=SubscriptionTier.PRO),
    )
    edits = Session().get(YetAIBet, "b1").prediction_factors["edits"]
    by_field = {e["field"]: e for e in edits}
    assert by_field["odds"]["old"] == -110 and by_field["odds"]["new"] == -125
    assert by_field["odds"]["by"] == 7 and by_field["odds"]["at"].endswith("Z")
    assert by_field["tier_requirement"]["new"] == "pro"  # enum serialized


def test_edit_to_ungradeable_selection_400_unchanged(Session):
    db = Session()
    db.add(_row())
    db.commit()
    with pytest.raises(HTTPException) as e:
        _edit(db, picks.EditPickRequest(selection="BOS ML"))
    assert e.value.status_code == 400
    bet = Session().get(YetAIBet, "b1")
    assert (
        bet.selection == "Boston Celtics -4.5" and "edits" not in bet.prediction_factors
    )


def test_edit_valid_selection_keeps_grading_in_audit(Session):
    grading = {"market": "spread", "league": "nba", "side": "home", "line": -4.5}
    db = Session()
    db.add(_row(prediction_factors={"grading": grading, "event_id": "e1"}))
    db.commit()
    _edit(db, picks.EditPickRequest(selection="Boston Celtics -3.5"))
    pf = Session().get(YetAIBet, "b1").prediction_factors
    assert "grading" not in pf and pf["event_id"] == "e1"
    (entry,) = pf["edits"]
    assert (
        entry["old"] == "Boston Celtics -4.5" and entry["new"] == "Boston Celtics -3.5"
    )
    assert entry["dropped_grading"] == grading


# ---------------------------------------------------------------- B12


def _expired_auto(id="a1"):
    return _row(
        id=id,
        status="expired",
        source=BetSource.AUTO,
        result="Admin expired (stale pick)",
        settled_at=datetime.utcnow(),
    )


def test_expired_auto_without_copy_left_alone(Session):
    db = Session()
    db.add(_expired_auto())
    db.commit()
    with patch.object(SERVICE, "_linked_unified_bets_for_yetai_pick", return_value=[]):
        assert SERVICE._admin_expired_shown(db, db.get(YetAIBet, "a1")) is False


def test_expired_auto_with_user_copy_voided(Session):
    db = Session()
    bet = _expired_auto()
    db.add(bet)
    db.commit()
    with (
        patch.object(
            SERVICE, "_linked_unified_bets_for_yetai_pick", return_value=[object()]
        ),
        patch.object(SERVICE, "mirror_to_linked_copies"),
    ):
        assert SERVICE._admin_expired_shown(db, bet) is True
        assert SERVICE._settle_one(db, bet, datetime.utcnow()) == "void"
    assert bet.status == "void"


def test_expired_manual_still_voided(Session):
    db = Session()
    bet = _expired_auto()
    bet.source = BetSource.MANUAL
    assert SERVICE._admin_expired_shown(db, bet) is True


# ---------------------------------------------------------------- B15


def test_game_date_is_eastern_day():
    bet = _row(ct=datetime(2026, 11, 14, 1, 30))
    assert game_date_for_yetai_bet(bet) == date(2026, 11, 13)
