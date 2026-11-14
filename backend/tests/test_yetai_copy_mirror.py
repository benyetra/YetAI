"""Linked user copies of a YetAI pick mirror the pick; no grader grades them directly (B5, B13)."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.database_models import BetType as PickBetType
from app.models.database_models import SubscriptionTier, YetAIBet
from app.models.simple_unified_bet_model import (
    BetStatus,
    BetType,
    OverUnder,
    SimpleUnifiedBet,
)
from app.services import yetai_grading as yg
from app.services.player_prop_verification_service import PlayerPropVerificationService
from app.services.unified_bet_verification_service import UnifiedBetVerificationService
from app.services.yetai_bets_service_db import YetAIBetsServiceDB

NOW = datetime.utcnow()


@compiles(JSONB, "sqlite")
def _jsonb(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    YetAIBet.__table__.create(engine)
    SimpleUnifiedBet.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def pick(db, **kw):
    kw.setdefault("id", "pick-1")
    kw.setdefault("status", "active")
    kw.setdefault("bet_type", PickBetType.MONEYLINE)
    kw.setdefault("selection", "Toronto Raptors ML")
    kw.setdefault("sport", "NBA")
    kw.setdefault("home_team", "Toronto Raptors")
    kw.setdefault("away_team", "Philadelphia 76ers")
    kw.setdefault("commence_time", NOW - timedelta(days=1))
    kw.setdefault("created_at", NOW - timedelta(days=2))
    bet = YetAIBet(
        title="t",
        description="",
        odds=-110,
        confidence=80,
        tier_requirement=SubscriptionTier.FREE,
        prediction_factors={},
        **kw,
    )
    db.add(bet)
    db.commit()
    return bet


def copy(db, pick_id="pick-1", **kw):
    kw.setdefault("id", "copy-1")
    kw.setdefault("bet_type", BetType.MONEYLINE)
    kw.setdefault("selection", "Toronto Raptors ML")
    kw.setdefault("sport", "NBA")
    kw.setdefault("home_team", "Toronto Raptors")
    kw.setdefault("away_team", "Philadelphia 76ers")
    kw.setdefault("commence_time", NOW - timedelta(days=1))
    kw.setdefault("status", BetStatus.PENDING)
    row = SimpleUnifiedBet(
        user_id=1,
        odds_api_event_id=f"yetai-pick-{pick_id}",
        yetai_bet_id=pick_id,
        amount=100.0,
        odds=-110,
        potential_win=90.0,
        **kw,
    )
    db.add(row)
    db.commit()
    return row


class O:
    def __init__(self, kind, result="r"):
        self.kind, self.result = kind, result


def settle(db, kind):
    """Run verify_pending_yetai_bets on this session with the grader forced to `kind`."""
    with (
        patch("app.services.yetai_bets_service_db.SessionLocal", return_value=db),
        patch.object(db, "close"),
        patch("app.services.yetai_grading.grade_pick", return_value=O(kind)),
    ):
        YetAIBetsServiceDB().verify_pending_yetai_bets()
    db.expire_all()


def test_settlement_mirrors_to_copy_in_same_run(db):
    pick(db)
    c = copy(db)
    settle(db, "won")
    assert c.status == BetStatus.WON and c.result_amount == 190.0


def test_correction_won_to_lost_and_back(db):
    p = pick(db)
    c = copy(db)
    settle(db, "won")
    svc = YetAIBetsServiceDB()
    p.status, p.settled_at = "lost", NOW
    assert svc.mirror_to_linked_copies(db, p) == 1
    assert c.status == BetStatus.LOST and c.result_amount == 0.0
    p.status = "won"
    svc.mirror_to_linked_copies(db, p)
    assert c.status == BetStatus.WON


def test_void_after_won_cancels_and_refunds(db):
    p = pick(db)
    c = copy(db)
    settle(db, "won")
    p.status, p.settled_at = "void", NOW
    YetAIBetsServiceDB().mirror_to_linked_copies(db, p)
    assert c.status == BetStatus.CANCELLED and c.result_amount == 100.0


def test_admin_reopen_puts_copy_back_to_pending(db):
    from app.api.admin_yetai_picks import reopen

    pick(db, status="lost", settled_at=NOW, result="x")
    c = copy(db, status=BetStatus.LOST, settled_at=NOW, result_amount=0.0)
    asyncio.run(reopen("pick-1", {}, db))
    db.expire_all()
    assert c.status == BetStatus.PENDING
    assert c.settled_at is None and c.result_amount is None


def test_admin_pull_voids_copy(db):
    from app.api.admin_yetai_picks import reject

    pick(db)
    c = copy(db)
    asyncio.run(reject("pick-1", {}, db))
    db.expire_all()
    assert c.status == BetStatus.CANCELLED and c.result_amount == 100.0


def test_settle_pending_props_does_not_grade_linked_copy(db):
    pick(db, sport="MLB", bet_type=PickBetType.PROP)
    c = copy(
        db, sport="MLB", bet_type=BetType.PROP, selection="Player Over 5.5 Strikeouts"
    )
    svc = PlayerPropVerificationService(db)
    with patch.object(
        svc, "_verify_single_mlb_prop", new=AsyncMock(return_value={"status": "lost"})
    ) as m:
        out = asyncio.run(svc.settle_pending_props_for_user(db, 1))
    assert out["settled"] == 0 and c.status == BetStatus.PENDING
    m.assert_not_called()


def test_unified_verification_ignores_linked_lost_mlb_copy(db):
    pick(db, sport="MLB", bet_type=PickBetType.PROP)
    c = copy(
        db, sport="MLB", bet_type=BetType.PROP, status=BetStatus.LOST, result_amount=0.0
    )
    svc = UnifiedBetVerificationService.__new__(UnifiedBetVerificationService)
    with (
        patch(
            "app.services.unified_bet_verification_service.SessionLocal",
            return_value=db,
        ),
        patch.object(db, "close"),
        patch.object(svc, "_verify_single_bet", new=AsyncMock()) as m,
    ):
        out = asyncio.run(svc.verify_all_pending_bets())
    m.assert_not_called()
    assert out["verified"] == 0 and c.status == BetStatus.LOST


def test_linked_moneyline_not_graded_by_game_grader(db):
    pick(db)
    c = copy(db)
    svc = UnifiedBetVerificationService.__new__(UnifiedBetVerificationService)
    svc.odds_service = AsyncMock()
    games = [{"completed": True, "home_team": "Toronto Raptors"}]
    assert asyncio.run(svc._verify_single_bet(c, games, db=db)) is None
    out = asyncio.run(_by_id(svc, db, c))
    assert out["success"] is False and c.status == BetStatus.PENDING


async def _by_id(svc, db, c):
    with (
        patch(
            "app.services.unified_bet_verification_service.SessionLocal",
            return_value=db,
        ),
        patch.object(db, "close"),
    ):
        return await svc.verify_bet_by_id(c.id)


def _unlinked_prop(db, **kw):
    kw.setdefault("commence_time", datetime(2026, 11, 14, 0, 30))
    row = SimpleUnifiedBet(
        id="solo",
        user_id=1,
        odds_api_event_id="evt",
        bet_type=BetType.PROP,
        amount=100.0,
        odds=-110,
        potential_win=90.0,
        selection="Player Over 5 Strikeouts",
        sport="MLB",
        home_team="a",
        away_team="b",
        placed_at=datetime(2026, 11, 14, 1, 0),
        **kw,
    )
    db.add(row)
    db.commit()
    return row


def test_unlinked_prop_uses_et_date_first(db):
    bet = _unlinked_prop(db)
    svc = PlayerPropVerificationService(db)
    assert svc._game_date_for_unified_prop(bet).isoformat() == "2026-11-13"


def test_integer_line_prop_pushes(db):
    bet = _unlinked_prop(db)
    svc = PlayerPropVerificationService(db)
    stats = {"strikeOuts": 5}
    with (
        patch.object(svc, "_fetch_mlb_player_stats", return_value=stats),
        patch.object(svc, "_resolve_mlb_game_pk", return_value=None),
        patch.object(svc, "_fetch_mlb_player_stats_from_boxscore", return_value=stats),
    ):
        res = asyncio.run(svc.verify_single_prop(bet))
    assert res and res["status"] == BetStatus.PUSHED
    assert res["result_amount"] == 100.0


def test_copy_of_deleted_pick_is_graded_on_its_own(db):
    # Picks could be hard-deleted before B1: a dangling yetai_bet_id has no pick to mirror.
    row = copy(db, pick_id="gone")
    service = PlayerPropVerificationService(db)
    assert not service.is_yetai_linked(row)
    pick(db)
    assert service.is_yetai_linked(copy(db, id="copy-2"))


def test_open_pick_leaves_live_copy_live(db):
    p = pick(db)
    row = copy(db, status=BetStatus.LIVE)
    assert not YetAIBetsServiceDB().sync_unified_from_yetai_pick(db, p, row)
    assert row.status == BetStatus.LIVE
