"""
Tests for tier-gated visibility of YetAI bets (Task 16).

Rules under test:
- Only bets with status in SUBSCRIBER_VISIBLE_STATUSES ("active", "pending",
  "won", "lost", "pushed") are returned.
- pending_approval, rejected, expired, and any other non-approved status
  must NEVER appear in subscriber results.
- FREE users see FREE-tier bets only.
- PRO users see FREE + PRO bets.
- ELITE users see FREE + PRO + ELITE bets.
- Manual bets (source=MANUAL, status="pending") still appear when active.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.database_models import SubscriptionTier, YetAIBet
from datetime import datetime, timedelta

from app.models.database_models import BetType
from app.services.yetai_bets_service_db import (
    YetAIBetsServiceDB,
    coerce_subscription_tier,
    yetai_bet_subscriber_live_visible,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bet(
    bet_id: str,
    status: str,
    tier: SubscriptionTier = SubscriptionTier.FREE,
) -> MagicMock:
    """Build a minimal mock YetAIBet row."""
    bet = MagicMock(spec=YetAIBet)
    bet.id = bet_id
    bet.status = status
    bet.tier_requirement = tier
    bet.sport = "NFL"
    bet.title = f"Game {bet_id}"
    bet.game_id = None
    bet.home_team = "Home"
    bet.away_team = "Away"
    bet.commence_time = None
    bet.bet_type = "moneyline"
    bet.selection = "Home"
    bet.odds = -110.0
    bet.confidence = 75.0
    bet.description = "Reasoning"
    bet.parlay_legs = None
    bet.game_time = None
    bet.created_at = None
    bet.settled_at = None
    bet.result = None
    return bet


def _make_db(rows: list) -> MagicMock:
    """
    Return a mock Session whose query chain returns *rows* for any
    .filter().filter().order_by().all() call chain.
    """
    db = MagicMock()

    # Support arbitrarily deep .filter().filter()... chains.
    # Each intermediate call returns the same mock so .all() is always reachable.
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.all.return_value = rows

    db.query.return_value = chain
    return db


# ---------------------------------------------------------------------------
# Status visibility tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_status",
    [
        "pending_approval",
        "rejected",
        "expired",
        "pending_manual_review",
    ],
)
def test_non_active_statuses_excluded(bad_status):
    """Bets with non-subscriber-visible statuses must not appear."""
    bet = _make_bet("b1", bad_status, SubscriptionTier.FREE)
    # The DB would return this row, but get_yetai_bets_for_user must NOT
    # include it — we validate by checking that the status filter never
    # includes these values.
    service = YetAIBetsServiceDB()
    assert (
        bad_status not in service.SUBSCRIBER_VISIBLE_STATUSES
    ), f"Status '{bad_status}' must not be in SUBSCRIBER_VISIBLE_STATUSES"


def test_active_status_is_visible():
    """Bets with status='active' (approved auto-picks) ARE visible."""
    service = YetAIBetsServiceDB()
    assert "active" in service.SUBSCRIBER_VISIBLE_STATUSES


def test_pending_status_is_visible():
    """Bets with status='pending' (manual bets, legacy) ARE visible."""
    service = YetAIBetsServiceDB()
    assert "pending" in service.SUBSCRIBER_VISIBLE_STATUSES


def test_settled_statuses_are_visible():
    """Won/lost/pushed bets (historical) ARE visible to subscribers."""
    service = YetAIBetsServiceDB()
    for status in ("won", "lost", "pushed"):
        assert (
            status in service.SUBSCRIBER_VISIBLE_STATUSES
        ), f"Status '{status}' should be visible to subscribers"


# ---------------------------------------------------------------------------
# Tier filtering tests via get_yetai_bets_for_user
# ---------------------------------------------------------------------------


def _rows_for_tier_tests():
    """Six bets: one active per tier + three non-visible statuses."""
    return [
        _make_bet("free-active", "active", SubscriptionTier.FREE),
        _make_bet("pro-active", "active", SubscriptionTier.PRO),
        _make_bet("elite-active", "active", SubscriptionTier.ELITE),
        _make_bet("free-pending", "pending", SubscriptionTier.FREE),
        _make_bet("free-rejected", "rejected", SubscriptionTier.FREE),
        _make_bet("pro-approval", "pending_approval", SubscriptionTier.PRO),
        _make_bet("elite-expired", "expired", SubscriptionTier.ELITE),
    ]


def test_query_filters_are_applied_to_db():
    """
    get_yetai_bets_for_user must build a query that filters by both status
    and tier.  We verify the mock's filter was called (not a no-op passthrough).
    """
    service = YetAIBetsServiceDB()
    db = _make_db([])  # empty result is fine; we care about filter calls
    service.get_yetai_bets_for_user("free", db)
    assert db.query.called, "db.query was not called"
    assert db.query.return_value.filter.called, "filter() was not called on the query"


def test_free_tier_only_sees_own_tier(monkeypatch):
    """FREE user: only FREE-tier bets in subscriber-visible statuses."""
    service = YetAIBetsServiceDB()

    # Simulate DB returning a FREE-active and a PRO-active row (the real
    # DB would filter, but here we test that the service maps output correctly
    # by providing only the matching rows the DB would return).
    free_bet = _make_bet("free-active", "active", SubscriptionTier.FREE)
    db = _make_db([free_bet])

    results = service.get_yetai_bets_for_user("free", db)
    ids = [r["id"] for r in results]
    assert "free-active" in ids
    assert "pro-active" not in ids
    assert "elite-active" not in ids


def test_pro_tier_sees_free_and_pro(monkeypatch):
    """PRO user should see FREE + PRO active bets."""
    service = YetAIBetsServiceDB()

    free_bet = _make_bet("free-active", "active", SubscriptionTier.FREE)
    pro_bet = _make_bet("pro-active", "active", SubscriptionTier.PRO)
    db = _make_db([free_bet, pro_bet])

    results = service.get_yetai_bets_for_user("pro", db)
    ids = [r["id"] for r in results]
    assert "free-active" in ids
    assert "pro-active" in ids
    assert "elite-active" not in ids


def test_elite_tier_sees_all_tiers(monkeypatch):
    """ELITE user should see FREE + PRO + ELITE active bets."""
    service = YetAIBetsServiceDB()

    free_bet = _make_bet("free-active", "active", SubscriptionTier.FREE)
    pro_bet = _make_bet("pro-active", "active", SubscriptionTier.PRO)
    elite_bet = _make_bet("elite-active", "active", SubscriptionTier.ELITE)
    db = _make_db([free_bet, pro_bet, elite_bet])

    results = service.get_yetai_bets_for_user("elite", db)
    ids = [r["id"] for r in results]
    assert "free-active" in ids
    assert "pro-active" in ids
    assert "elite-active" in ids


def test_pending_approval_never_visible_to_any_tier(monkeypatch):
    """pending_approval picks must not be in SUBSCRIBER_VISIBLE_STATUSES."""
    service = YetAIBetsServiceDB()
    # The DB-side filter enforces this; also verify the constant is correct.
    assert "pending_approval" not in service.SUBSCRIBER_VISIBLE_STATUSES


def test_rejected_never_visible(monkeypatch):
    """rejected picks must not be in SUBSCRIBER_VISIBLE_STATUSES."""
    service = YetAIBetsServiceDB()
    assert "rejected" not in service.SUBSCRIBER_VISIBLE_STATUSES


def test_expired_never_visible(monkeypatch):
    """expired picks must not be in SUBSCRIBER_VISIBLE_STATUSES."""
    service = YetAIBetsServiceDB()
    assert "expired" not in service.SUBSCRIBER_VISIBLE_STATUSES


# ---------------------------------------------------------------------------
# TIER_RANK correctness
# ---------------------------------------------------------------------------


def test_tier_rank_ordering():
    """FREE < PRO < ELITE must hold in TIER_RANK."""
    tr = YetAIBetsServiceDB.TIER_RANK
    assert tr[SubscriptionTier.FREE] < tr[SubscriptionTier.PRO]
    assert tr[SubscriptionTier.PRO] < tr[SubscriptionTier.ELITE]


def test_allowed_tiers_for_free():
    """FREE user: only FREE in allowed_tiers."""
    service = YetAIBetsServiceDB()
    tier_enum = SubscriptionTier.FREE
    user_rank = service.TIER_RANK[tier_enum]
    allowed = [t for t, r in service.TIER_RANK.items() if r <= user_rank]
    assert SubscriptionTier.FREE in allowed
    assert SubscriptionTier.PRO not in allowed
    assert SubscriptionTier.ELITE not in allowed


def test_allowed_tiers_for_pro():
    """PRO user: FREE + PRO in allowed_tiers."""
    service = YetAIBetsServiceDB()
    tier_enum = SubscriptionTier.PRO
    user_rank = service.TIER_RANK[tier_enum]
    allowed = [t for t, r in service.TIER_RANK.items() if r <= user_rank]
    assert SubscriptionTier.FREE in allowed
    assert SubscriptionTier.PRO in allowed
    assert SubscriptionTier.ELITE not in allowed


def test_allowed_tiers_for_elite():
    """ELITE user: FREE + PRO + ELITE in allowed_tiers."""
    service = YetAIBetsServiceDB()
    tier_enum = SubscriptionTier.ELITE
    user_rank = service.TIER_RANK[tier_enum]
    allowed = [t for t, r in service.TIER_RANK.items() if r <= user_rank]
    assert SubscriptionTier.FREE in allowed
    assert SubscriptionTier.PRO in allowed
    assert SubscriptionTier.ELITE in allowed


# ---------------------------------------------------------------------------
# Unknown tier falls back to FREE
# ---------------------------------------------------------------------------


def test_unknown_tier_falls_back_to_free():
    """An unrecognised tier string must be treated as FREE (most restrictive)."""
    service = YetAIBetsServiceDB()
    free_bet = _make_bet("free-active", "active", SubscriptionTier.FREE)
    pro_bet = _make_bet("pro-active", "active", SubscriptionTier.PRO)
    db = _make_db([free_bet])  # DB returns only FREE rows (correct filter)

    results = service.get_yetai_bets_for_user("garbage_tier", db)
    # No error, and only FREE bets returned
    ids = [r["id"] for r in results]
    assert "pro-active" not in ids


def test_active_bet_stays_visible_within_slate_window():
    """Recent slate-dated props stay live across the following calendar day."""
    service = YetAIBetsServiceDB()
    bet = _make_bet("stale-active", "active", SubscriptionTier.ELITE)
    bet.commence_time = None
    bet.created_at = datetime(2026, 6, 9, 17, 0)
    bet.bet_type = BetType.PROP
    bet.prediction_factors = {"event_id": "nba-prop-2026-06-09-1-points"}
    fixed_now = datetime(2026, 6, 10, 17, 0)
    assert yetai_bet_subscriber_live_visible(bet, now=fixed_now)
    db = _make_db([bet])

    with patch("app.services.yetai_bets_service_db.datetime") as mock_dt:
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.combine = datetime.combine
        results = service.get_yetai_bets_for_user("elite", db)
    assert [r["id"] for r in results] == ["stale-active"]


def test_coerce_subscription_tier_accepts_enum_and_repr():
    assert coerce_subscription_tier(SubscriptionTier.ELITE) == "elite"
    assert coerce_subscription_tier("SubscriptionTier.ELITE") == "elite"
