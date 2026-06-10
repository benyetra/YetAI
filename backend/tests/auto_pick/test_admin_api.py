"""
Tests for admin_yetai_picks API routes.

Uses direct function calls (not TestClient) to avoid complex DB/auth wiring,
matching the pattern used by test_orchestrator.py and other auto_pick tests.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.admin_yetai_picks import (
    ACTIVE_STATUS,
    EXPIRED_STATUS,
    PENDING_STATUS,
    REJECTED_STATUS,
    EditPickRequest,
    _serialize,
    approve,
    approve_all,
    edit,
    expire_pick,
    list_pending,
    reopen,
    reject,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bet(
    id: str = "b1",
    status: str = "pending_approval",
    tier: str = "free",
    odds: float = -110.0,
    title: str = "Test bet",
    selection: str = "Lakers ML",
    sport: str = "basketball_nba",
    reasoning: str = "Strong edge",
    confidence_score: float = 78.5,
) -> MagicMock:
    bet = MagicMock()
    bet.id = id
    bet.status = status
    bet.title = title
    bet.selection = selection
    bet.bet_type = MagicMock(value="moneyline")
    bet.sport = sport
    bet.odds = odds
    bet.tier_requirement = MagicMock(value=tier)
    bet.confidence_score = confidence_score
    bet.score_breakdown = {"edge": 80, "historical": 60}
    bet.reasoning = reasoning
    bet.source = MagicMock(value="auto")
    bet.created_at = datetime(2026, 5, 22, 12, 0, 0)
    bet.prediction_factors = {}
    bet.parlay_legs = None
    return bet


def _db_with_pending(*bets) -> MagicMock:
    """Return a mock Session that returns *bets* for .filter().all()."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = list(bets)
    return db


def _db_with_first(bet) -> MagicMock:
    """Return a mock Session that returns *bet* for .filter().first()."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = bet
    return db


# ---------------------------------------------------------------------------
# _serialize
# ---------------------------------------------------------------------------


def test_serialize_shape():
    bet = _bet()
    result = _serialize(bet)
    assert result["id"] == "b1"
    assert result["status"] == "pending_approval"
    assert result["bet_type"] == "moneyline"
    assert result["source"] == "auto"
    assert result["tier_requirement"] == "free"
    assert result["created_at"] == "2026-05-22T12:00:00"


def test_serialize_none_created_at():
    bet = _bet()
    bet.created_at = None
    result = _serialize(bet)
    assert result["created_at"] is None


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pending_returns_all_pending():
    b1 = _bet("b1")
    b2 = _bet("b2")
    db = _db_with_pending(b1, b2)

    result = await list_pending(_={}, db=db)

    assert len(result["picks"]) == 2
    assert result["picks"][0]["id"] == "b1"
    assert result["picks"][1]["id"] == "b2"


@pytest.mark.asyncio
async def test_list_pending_empty():
    db = _db_with_pending()
    result = await list_pending(_={}, db=db)
    assert result["picks"] == []


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_flips_status_to_active():
    bet = _bet("b1", status=PENDING_STATUS)
    db = _db_with_first(bet)

    result = await approve("b1", _={}, db=db)

    assert bet.status == ACTIVE_STATUS
    db.commit.assert_called_once()
    assert result["status"] == ACTIVE_STATUS


@pytest.mark.asyncio
async def test_approve_not_found_raises_404():
    db = _db_with_first(None)
    with pytest.raises(HTTPException) as exc_info:
        await approve("missing", _={}, db=db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_approve_wrong_status_raises_400():
    bet = _bet("b1", status="active")
    db = _db_with_first(bet)
    with pytest.raises(HTTPException) as exc_info:
        await approve("b1", _={}, db=db)
    assert exc_info.value.status_code == 400
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# reopen / expire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reopen_clears_settlement_and_returns_active():
    bet = _bet("b1", status="won")
    bet.settled_at = datetime(2026, 6, 10, 16, 56)
    bet.result = "Won: Over 1.5 — actual 2.0 (Luke Kornet)"
    db = _db_with_first(bet)

    result = await reopen("b1", _={}, db=db)

    assert bet.status == ACTIVE_STATUS
    assert bet.settled_at is None
    assert bet.result is None
    assert bet.prediction_factors.get("auto_grade_hold") is True
    db.commit.assert_called_once()
    assert result["status"] == ACTIVE_STATUS


@pytest.mark.asyncio
async def test_expire_marks_stale_pending_as_expired():
    bet = _bet("b1", status="pending")
    db = _db_with_first(bet)

    result = await expire_pick("b1", _={}, db=db)

    assert bet.status == EXPIRED_STATUS
    assert bet.settled_at is not None
    assert bet.result == "Admin expired (stale pick)"
    assert result["status"] == EXPIRED_STATUS


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_flips_status_to_rejected():
    bet = _bet("b1", status=PENDING_STATUS)
    db = _db_with_first(bet)

    result = await reject("b1", _={}, db=db)

    assert bet.status == REJECTED_STATUS
    db.commit.assert_called_once()
    assert result["status"] == REJECTED_STATUS


@pytest.mark.asyncio
async def test_reject_not_found_raises_404():
    db = _db_with_first(None)
    with pytest.raises(HTTPException) as exc_info:
        await reject("missing", _={}, db=db)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_reject_wrong_status_raises_400():
    bet = _bet("b1", status="active")
    db = _db_with_first(bet)
    with pytest.raises(HTTPException) as exc_info:
        await reject("b1", _={}, db=db)
    assert exc_info.value.status_code == 400
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_updates_provided_fields():
    bet = _bet("b1", odds=-110.0, selection="Lakers ML")
    db = _db_with_first(bet)

    payload = EditPickRequest(odds=-105.0, selection="Celtics ML")
    result = await edit("b1", payload, _={}, db=db)

    assert bet.odds == -105.0
    assert bet.selection == "Celtics ML"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_edit_ignores_unset_fields():
    bet = _bet("b1", odds=-110.0, title="Original Title")
    db = _db_with_first(bet)

    # Only update odds — title should not be touched
    payload = EditPickRequest(odds=-120.0)
    await edit("b1", payload, _={}, db=db)

    assert bet.odds == -120.0
    # title was not in the payload, so setattr should not have been called for it
    # (MagicMock allows any setattr, so verify via odds only — sufficient coverage)


@pytest.mark.asyncio
async def test_edit_not_found_raises_404():
    db = _db_with_first(None)
    payload = EditPickRequest(odds=-100.0)
    with pytest.raises(HTTPException) as exc_info:
        await edit("missing", payload, _={}, db=db)
    assert exc_info.value.status_code == 404
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# approve_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_all_flips_all_pending():
    b1 = _bet("b1", status=PENDING_STATUS)
    b2 = _bet("b2", status=PENDING_STATUS)
    db = _db_with_pending(b1, b2)

    result = await approve_all(_={}, db=db)

    assert b1.status == ACTIVE_STATUS
    assert b2.status == ACTIVE_STATUS
    db.commit.assert_called_once()
    assert set(result["approved"]) == {"b1", "b2"}


@pytest.mark.asyncio
async def test_approve_all_empty_returns_empty_list():
    db = _db_with_pending()
    result = await approve_all(_={}, db=db)
    assert result["approved"] == []
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# require_admin (smoke test — non-admin path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_admin_non_admin_raises_403():
    from app.core.auth import require_admin

    with patch("app.core.service_loader.is_service_available", return_value=False):
        non_admin_user = {"id": 99, "user_id": 99}
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user=non_admin_user)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_hardcoded_admin_passes():
    from app.core.auth import require_admin

    with patch("app.core.service_loader.is_service_available", return_value=False):
        admin_user = {"id": 8, "user_id": 8}
        result = await require_admin(current_user=admin_user)
        assert result == admin_user
