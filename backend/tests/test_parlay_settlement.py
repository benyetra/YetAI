"""Parlay parent settlement after legs are resolved."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# unified_bet_verification_service imports aiohttp transitively
sys.modules.setdefault("aiohttp", MagicMock())

from app.models.simple_unified_bet_model import BetStatus
from app.services.unified_bet_verification_service import UnifiedBetVerificationService


def _leg(status: BetStatus, leg_position: int = 1):
    return SimpleNamespace(
        status=status,
        leg_position=leg_position,
        parent_bet_id="parlay-1",
    )


def _parlay_parent():
    return SimpleNamespace(
        id="parlay-1",
        amount=50.0,
        potential_win=132.23,
        is_parlay=True,
        status=BetStatus.PENDING,
        parlay_legs=None,
    )


def test_evaluate_parlay_loses_when_any_leg_lost():
    service = UnifiedBetVerificationService()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _leg(BetStatus.WON, 1),
        _leg(BetStatus.LOST, 2),
    ]

    status, result_amount, reasoning = service._evaluate_parlay(_parlay_parent(), db=db)

    assert status == BetStatus.LOST
    assert result_amount == 0.0
    assert "lost" in reasoning.lower()


def test_evaluate_parlay_wins_when_all_active_legs_won():
    service = UnifiedBetVerificationService()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _leg(BetStatus.WON, 1),
        _leg(BetStatus.WON, 2),
    ]

    status, result_amount, reasoning = service._evaluate_parlay(_parlay_parent(), db=db)

    assert status == BetStatus.WON
    assert result_amount == 50.0 + 132.23
    assert "won" in reasoning.lower()


def test_evaluate_parlay_stays_pending_while_leg_pending():
    service = UnifiedBetVerificationService()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _leg(BetStatus.WON, 1),
        _leg(BetStatus.PENDING, 2),
    ]

    status, _, reasoning = service._evaluate_parlay(_parlay_parent(), db=db)

    assert status == BetStatus.PENDING
    assert "pending" in reasoning.lower()


def test_reconcile_pending_parlay_parents_skips_still_pending_parlays():
    service = UnifiedBetVerificationService()
    parent = _parlay_parent()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [parent]
    service._evaluate_parlay = MagicMock(
        return_value=(BetStatus.PENDING, 0.0, "Parlay pending: 1 legs still pending")
    )

    results = service._reconcile_pending_parlay_parents(db)

    assert results == []
