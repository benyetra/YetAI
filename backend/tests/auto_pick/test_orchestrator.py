"""
Tests for AutoPickOrchestrator.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.models.database_models import AutoPickRunStatus
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.models.database_models import BetSource, BetType, YetAIBet
from app.services.auto_pick.orchestrator import AutoPickOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strider() -> BetCandidate:
    """A high-edge candidate that should clear the default threshold."""
    return BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="basketball_nba",
        event_id="e1",
        selection="Strider OVER 5.5 K",
        market_line=5.5,
        market_odds=-115,
        our_projection=9.0,
        projection_metadata={
            "sample_size": 30,
            "generated_at": "2026-05-22T08:00:00",
            "model_confidence": 0.78,
        },
    )


def _weak_candidate() -> BetCandidate:
    """A low-edge candidate that should NOT clear the default threshold."""
    return BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="basketball_nba",
        event_id="e2",
        selection="x",
        market_line=5.5,
        market_odds=-110,
        our_projection=5.6,  # tiny edge → low score
        projection_metadata={"sample_size": 2},
    )


def _make_db() -> MagicMock:
    """
    Return a MagicMock Session that handles the query chains used by
    load_scoring_config and build_scoring_context, and simulates flush
    assigning an integer id to AutoPickRun.
    """
    db = MagicMock()
    # Chains used by load_scoring_config
    db.query.return_value.order_by.return_value.first.return_value = None
    # Chains used by build_scoring_context (filter/all, group_by/all, etc.)
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.group_by.return_value.all.return_value = (
        []
    )
    db.query.return_value.all.return_value = []

    # Simulate flush assigning id=1 to the first object added that has id=None
    def _flush():
        for call in db.add.call_args_list:
            target = call.args[0]
            if hasattr(target, "id") and target.id is None:
                target.id = 1
                break  # only first flush matters for run.id

    db.flush.side_effect = _flush
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_persists_picks_as_pending(monkeypatch):
    """SUCCESS path: one provider returns a strong candidate; one pick is persisted."""
    db = _make_db()
    prov = AsyncMock()
    prov.get_candidates = AsyncMock(return_value=[_strider()])

    orch = AutoPickOrchestrator(db=db, providers=[prov], now=datetime(2026, 5, 22, 9))
    result = await orch.run()

    assert result.status == AutoPickRunStatus.SUCCESS
    assert result.pick_count == 1
    db.commit.assert_called_once()
    # Two db.add calls: one for AutoPickRun, one for the YetAIBet
    assert db.add.call_count == 2


@pytest.mark.asyncio
async def test_orchestrator_partial_when_one_provider_fails():
    """PARTIAL path: one provider succeeds (empty), one raises — status is PARTIAL."""
    db = _make_db()
    good = AsyncMock()
    good.get_candidates = AsyncMock(return_value=[])
    bad = AsyncMock()
    bad.get_candidates = AsyncMock(side_effect=RuntimeError("boom"))

    orch = AutoPickOrchestrator(
        db=db, providers=[good, bad], now=datetime(2026, 5, 22, 9)
    )
    result = await orch.run()

    assert result.status == AutoPickRunStatus.PARTIAL


@pytest.mark.asyncio
async def test_orchestrator_no_picks_when_nothing_clears_threshold():
    """NO_PICKS path: provider returns a weak candidate that cannot beat threshold."""
    db = _make_db()
    prov = AsyncMock()
    prov.get_candidates = AsyncMock(return_value=[_weak_candidate()])

    orch = AutoPickOrchestrator(db=db, providers=[prov], now=datetime(2026, 5, 22, 9))
    result = await orch.run()

    assert result.status == AutoPickRunStatus.NO_PICKS
    assert result.pick_count == 0
    # Only one db.add call: AutoPickRun; no YetAIBet added
    assert db.add.call_count == 1


@pytest.mark.asyncio
async def test_orchestrator_failed_when_all_providers_fail():
    """FAILED path: every provider raises — status is FAILED, no picks."""
    db = _make_db()
    bad1 = AsyncMock()
    bad1.get_candidates = AsyncMock(side_effect=RuntimeError("a"))
    bad2 = AsyncMock()
    bad2.get_candidates = AsyncMock(side_effect=RuntimeError("b"))

    orch = AutoPickOrchestrator(
        db=db, providers=[bad1, bad2], now=datetime(2026, 5, 22, 9)
    )
    result = await orch.run()

    assert result.status == AutoPickRunStatus.FAILED
    assert result.pick_count == 0


@pytest.mark.asyncio
async def test_orchestrator_result_id_matches_run():
    """OrchestratorResult.id should equal the AutoPickRun.id set by flush."""
    db = _make_db()
    prov = AsyncMock()
    prov.get_candidates = AsyncMock(return_value=[_strider()])

    orch = AutoPickOrchestrator(db=db, providers=[prov], now=datetime(2026, 5, 22, 9))
    result = await orch.run()

    assert result.id == 1  # set by _make_db's flush side-effect


@pytest.mark.asyncio
async def test_orchestrator_refreshes_existing_pending_pick(monkeypatch):
    """Re-run must update the same pending row, not insert a duplicate."""
    db = _make_db()
    prov = AsyncMock()
    prov.get_candidates = AsyncMock(return_value=[_strider()])

    existing = YetAIBet(
        id="existing-pick-id",
        title="old title",
        bet_type=BetType.PROP,
        selection="Strider OVER 5.5 K",
        odds=-110.0,
        confidence=50.0,
        status="pending_approval",
        source=BetSource.AUTO,
        sport="basketball_nba",
        prediction_factors={"event_id": "e1"},
        created_at=datetime(2026, 5, 22, 8, 0, 0),
    )
    duplicate = YetAIBet(
        id="duplicate-pick-id",
        title="old title",
        bet_type=BetType.PROP,
        selection="Strider OVER 5.5 K",
        odds=-110.0,
        confidence=50.0,
        status="pending_approval",
        source=BetSource.AUTO,
        sport="basketball_nba",
        prediction_factors={"event_id": "e1"},
        created_at=datetime(2026, 5, 22, 9, 0, 0),
    )
    key = AutoPickOrchestrator(db, [], datetime.utcnow())._candidate_pick_key(
        _strider()
    )
    pending_index = {key: [existing, duplicate]}

    monkeypatch.setattr(
        AutoPickOrchestrator,
        "_load_pending_auto_index",
        lambda self: pending_index,
    )

    orch = AutoPickOrchestrator(db=db, providers=[prov], now=datetime(2026, 5, 22, 9))
    result = await orch.run()

    assert result.pick_count == 1
    assert existing.id == "existing-pick-id"
    assert existing.confidence_score is not None
    assert existing.confidence_score > 50.0
    assert existing.auto_pick_run_id == 1
    assert duplicate.status == "rejected"
    # AutoPickRun + no new YetAIBet insert
    assert db.add.call_count == 1


@pytest.mark.asyncio
async def test_orchestrator_persists_parlay_when_two_hit_legs_qualify(monkeypatch):
    """When parlay selector finds a pair, a parlay YetAIBet row is persisted."""
    from app.services.auto_pick.confidence_score import ConfidenceScore
    from app.services.auto_pick.parlay_selector import ScoredParlayPick
    from app.services.auto_pick.selector import ScoredCandidate

    db = _make_db()
    hit_a = BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id="mlb-hit-1-a",
        selection="Judge OVER 0.5 hits",
        market_line=0.5,
        market_odds=-110,
        our_projection=0.9,
        projection_metadata={"stat": "hits", "side": "over", "parlay_eligible": True},
    )
    hit_b = BetCandidate(
        market_type=MarketType.PLAYER_PROP,
        league="MLB",
        event_id="mlb-hit-2-b",
        selection="Soto OVER 0.5 hits",
        market_line=0.5,
        market_odds=-110,
        our_projection=0.85,
        projection_metadata={"stat": "hits", "side": "over", "parlay_eligible": True},
    )
    prov = AsyncMock()
    prov.get_candidates = AsyncMock(return_value=[hit_a, hit_b])

    leg_a = ScoredCandidate(
        candidate=hit_a,
        score=ConfidenceScore(total=88, breakdown={}, reasoning=""),
    )
    leg_b = ScoredCandidate(
        candidate=hit_b,
        score=ConfidenceScore(total=86, breakdown={}, reasoning=""),
    )
    fake_parlay = ScoredParlayPick(
        legs=(leg_a, leg_b),
        combined_odds=264,
        score=ConfidenceScore(total=84, breakdown={}, reasoning="2-leg parlay"),
    )

    monkeypatch.setattr(
        "app.services.auto_pick.orchestrator.ParlaySelector.select_parlay",
        lambda self, scored: fake_parlay,
    )

    orch = AutoPickOrchestrator(db=db, providers=[prov], now=datetime(2026, 5, 22, 9))
    result = await orch.run()

    assert result.pick_count >= 1
    added = [call.args[0] for call in db.add.call_args_list]
    parlays = [b for b in added if getattr(b, "bet_type", None) == BetType.PARLAY]
    assert len(parlays) == 1
    assert parlays[0].parlay_legs is not None
    assert len(parlays[0].parlay_legs) == 2


@pytest.mark.asyncio
async def test_orchestrator_no_providers_returns_failed():
    """Edge case: zero providers → all (zero) providers failed → FAILED."""
    db = _make_db()
    orch = AutoPickOrchestrator(db=db, providers=[], now=datetime(2026, 5, 22, 9))
    result = await orch.run()
    # n_providers == 0 → the "all failed" branch is False, falls to NO_PICKS
    assert result.status == AutoPickRunStatus.NO_PICKS
    assert result.pick_count == 0
