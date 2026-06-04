"""
AutoPickOrchestrator: coordinates candidate collection, scoring, selection,
and persistence for automated bet picks.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.database_models import (
    AutoPickRun,
    AutoPickRunStatus,
    BetSource,
    BetType,
    YetAIBet,
)
from app.services.auto_pick.candidate import BetCandidate, DateRange, MarketType
from app.services.auto_pick.config_loader import load_scoring_config
from app.services.auto_pick.context_builder import build_scoring_context
from app.services.auto_pick.scorer import ConfidenceScorer
from app.services.auto_pick.parlay_selector import ParlaySelector, ScoredParlayPick
from app.services.auto_pick.selector import BetSelector, ScoredCandidate, SelectorConfig
from app.services.yetai_bets_display import game_label_for_matchup
from app.services.yetai_bets_service_db import clamp_yetai_result

log = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def display_matchup_title(candidate: BetCandidate) -> str:
    """Game line for subscriber UI (maps to API ``game`` / DesignPick ``matchup``)."""
    market = candidate.market_type
    bet_type = None
    if market == MarketType.PLAYER_PROP:
        bet_type = "prop"
    return game_label_for_matchup(
        away_team=candidate.away_team,
        home_team=candidate.home_team,
        sport=candidate.league,
        bet_type=bet_type,
        projection_metadata=candidate.projection_metadata,
    )


def pending_parlay_key(*, strategy: str, sport: str) -> tuple[str, str, str, str]:
    """Stable identity for pending auto parlays (one slot per strategy/sport)."""
    return (BetType.PARLAY.value, sport or "", strategy, "auto-parlay")


def pending_pick_key(
    *,
    selection: str,
    sport: str,
    bet_type: BetType,
    event_id: str,
) -> tuple[str, str, str, str]:
    """Stable identity for pending auto-picks (see design spec idempotency)."""
    return (bet_type.value, sport or "", event_id or "", selection)


def date_range_for_utc_day(now: datetime) -> DateRange:
    """Inclusive UTC calendar-day bounds for projection source queries.

    Using bare ``utcnow()`` as the lower bound breaks SQL ``date >= timestamp``
    comparisons (date at midnight is less than an afternoon timestamp).
    """
    run_day = now.date()
    return DateRange(
        start=datetime.combine(run_day, time.min),
        end=datetime.combine(run_day, time.max),
    )


# Map auto-pick MarketType -> YetAIBet BetType enum
_MARKET_TYPE_TO_BET_TYPE: dict[MarketType, BetType] = {
    MarketType.MONEYLINE: BetType.MONEYLINE,
    MarketType.SPREAD: BetType.SPREAD,
    MarketType.TOTAL: BetType.TOTAL,
    MarketType.PLAYER_PROP: BetType.PROP,
}


@dataclass
class OrchestratorResult:
    id: int
    status: AutoPickRunStatus
    pick_count: int


class AutoPickOrchestrator:
    """
    Coordinates the full auto-pick pipeline:
      1. Load scoring config from DB (or defaults).
      2. Build scoring context (recent history, line movements, etc.).
      3. Fan out to all registered providers in parallel.
      4. Score every candidate with ConfidenceScorer.
      5. Run BetSelector to filter/rank/tier.
      6. Persist YetAIBet rows (status="pending_approval", source=AUTO).
      7. Write an AutoPickRun audit row.
    """

    def __init__(
        self,
        db: Session,
        providers: list,
        now: datetime,
        scorer: Optional[ConfidenceScorer] = None,
    ) -> None:
        self.db = db
        self.providers = providers
        self.now = now
        self.scorer = scorer or ConfidenceScorer()

    async def run(self) -> OrchestratorResult:
        cfg = load_scoring_config(self.db)
        ctx = build_scoring_context(self.db, cfg, self.now)

        selector_config = SelectorConfig(
            threshold=cfg.score_threshold,
            odds_min=cfg.odds_min,
            odds_max=cfg.odds_max,
            max_picks=cfg.max_picks,
        )
        selector = BetSelector(selector_config)
        parlay_selector = ParlaySelector(selector_config)

        date_range = date_range_for_utc_day(self.now)

        results = await asyncio.gather(
            *[self._safe_get(p, date_range) for p in self.providers],
            return_exceptions=False,
        )

        provider_failures = sum(1 for r in results if r is None)
        all_candidates: list[BetCandidate] = []
        for r in results:
            if r is not None:
                all_candidates.extend(r)

        scored = [
            ScoredCandidate(candidate=c, score=self.scorer.score(c, ctx))
            for c in all_candidates
        ]
        picks = selector.select(scored)
        parlay_pick = parlay_selector.select_parlay(scored)
        total_picks = len(picks) + (1 if parlay_pick else 0)

        status = self._compute_status(
            n_picks=total_picks,
            fails=provider_failures,
            n_providers=len(self.providers),
        )

        run = AutoPickRun(
            run_at=self.now,
            status=status,
            candidates_considered=len(all_candidates),
            candidates_selected=total_picks,
            dropped_reasons={
                sc.candidate.event_id: sc.drop_reason for sc in scored if sc.drop_reason
            },
            error=None,
        )
        self.db.add(run)
        self.db.flush()  # populates run.id

        pending_by_key = self._load_pending_auto_index()
        for p in picks:
            self._upsert_pick(p, run.id, pending_by_key)
        if parlay_pick:
            self._upsert_parlay_pick(parlay_pick, run.id, pending_by_key)

        self.db.commit()
        log.info(
            "auto_pick run %s: %s straight + %s parlay, status=%s",
            run.id,
            len(picks),
            1 if parlay_pick else 0,
            status,
        )
        return OrchestratorResult(id=run.id, status=status, pick_count=total_picks)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _safe_get(
        self, provider, date_range: DateRange
    ) -> Optional[list[BetCandidate]]:
        """Invoke a provider, returning None on any exception."""
        try:
            return await provider.get_candidates(date_range)
        except Exception:
            log.exception("provider %s failed", type(provider).__name__)
            return None

    @staticmethod
    def _compute_status(
        n_picks: int, fails: int, n_providers: int
    ) -> AutoPickRunStatus:
        if n_providers > 0 and fails == n_providers:
            return AutoPickRunStatus.FAILED
        if fails > 0:
            return AutoPickRunStatus.PARTIAL
        if n_picks == 0:
            return AutoPickRunStatus.NO_PICKS
        return AutoPickRunStatus.SUCCESS

    def _candidate_pick_key(self, c: BetCandidate) -> tuple[str, str, str, str]:
        bet_type = _MARKET_TYPE_TO_BET_TYPE.get(c.market_type, BetType.PROP)
        return pending_pick_key(
            selection=c.selection,
            sport=c.league,
            bet_type=bet_type,
            event_id=c.event_id,
        )

    @staticmethod
    def _bet_row_pick_key(bet: YetAIBet) -> tuple[str, str, str, str]:
        event_id = ""
        if isinstance(bet.prediction_factors, dict):
            event_id = str(bet.prediction_factors.get("event_id") or "")
        return pending_pick_key(
            selection=bet.selection or "",
            sport=bet.sport or "",
            bet_type=bet.bet_type or BetType.PROP,
            event_id=event_id,
        )

    def _load_pending_auto_index(
        self,
    ) -> dict[tuple[str, str, str, str], list[YetAIBet]]:
        rows = (
            self.db.query(YetAIBet)
            .filter(
                YetAIBet.status == "pending_approval",
                YetAIBet.source == BetSource.AUTO,
            )
            .all()
        )
        index: dict[tuple[str, str, str, str], list[YetAIBet]] = {}
        for bet in rows:
            index.setdefault(self._bet_row_pick_key(bet), []).append(bet)
        return index

    def _upsert_parlay_pick(
        self,
        p: ScoredParlayPick,
        run_id: int,
        pending_by_key: dict[tuple[str, str, str, str], list[YetAIBet]],
    ) -> None:
        key = pending_parlay_key(strategy="mlb_2leg_hits", sport="MLB")
        existing = pending_by_key.get(key, [])
        if existing:
            primary = min(
                existing,
                key=lambda b: b.created_at or datetime.min,
            )
            self._apply_parlay_fields(primary, p, run_id)
            for dup in existing:
                if dup.id != primary.id:
                    dup.status = "rejected"
                    dup.result = clamp_yetai_result("Superseded by newer auto-pick run")
            log.info("auto_pick refreshed pending parlay %s (key=%s)", primary.id, key)
            return

        bet = self._build_parlay_bet(p, run_id)
        self.db.add(bet)
        pending_by_key.setdefault(key, []).append(bet)

    def _apply_parlay_fields(
        self, bet: YetAIBet, p: ScoredParlayPick, run_id: int
    ) -> None:
        fresh = self._build_parlay_bet(p, run_id)
        for field in (
            "title",
            "description",
            "bet_type",
            "selection",
            "odds",
            "confidence",
            "status",
            "source",
            "tier_requirement",
            "confidence_score",
            "score_breakdown",
            "reasoning",
            "auto_pick_run_id",
            "sport",
            "home_team",
            "away_team",
            "commence_time",
            "prediction_factors",
            "parlay_legs",
        ):
            setattr(bet, field, getattr(fresh, field))

    def _build_parlay_leg_dict(self, leg: ScoredCandidate) -> dict:
        c = leg.candidate
        game_label = display_matchup_title(c)
        odds_str = f"+{c.market_odds}" if c.market_odds > 0 else str(c.market_odds)
        return _json_safe(
            {
                "sport": c.league,
                "game": game_label,
                "game_id": c.event_id,
                "home_team": c.home_team,
                "away_team": c.away_team,
                "bet_type": "Player Prop",
                "pick": c.selection,
                "odds": odds_str,
                "confidence": int(round(leg.score.total)),
                "commence_time": (
                    c.commence_time.isoformat() if c.commence_time else None
                ),
                "reasoning": leg.score.reasoning or "",
            }
        )

    def _build_parlay_bet(self, p: ScoredParlayPick, run_id: int) -> YetAIBet:
        leg_a, leg_b = p.legs
        s = p.score
        legs_json = [
            self._build_parlay_leg_dict(leg_a),
            self._build_parlay_leg_dict(leg_b),
        ]
        earliest_commence = leg_a.candidate.commence_time
        if leg_b.candidate.commence_time and (
            earliest_commence is None
            or leg_b.candidate.commence_time < earliest_commence
        ):
            earliest_commence = leg_b.candidate.commence_time

        combined_str = (
            f"+{p.combined_odds}" if p.combined_odds > 0 else str(p.combined_odds)
        )
        title = f"MLB 2-Leg Hit Parlay ({combined_str})"
        reasoning_text = s.reasoning or ""

        return YetAIBet(
            id=str(uuid.uuid4()),
            title=title,
            description=reasoning_text,
            bet_type=BetType.PARLAY,
            selection="2-Leg Parlay",
            odds=float(p.combined_odds),
            confidence=s.total,
            status="pending_approval",
            source=BetSource.AUTO,
            tier_requirement=p.tier,
            confidence_score=s.total,
            score_breakdown=s.breakdown,
            reasoning=reasoning_text,
            auto_pick_run_id=run_id,
            sport="MLB",
            home_team=None,
            away_team=None,
            commence_time=earliest_commence,
            parlay_legs=legs_json,
            prediction_factors=_json_safe(
                {
                    "strategy": "mlb_2leg_hits",
                    "combined_odds": p.combined_odds,
                    "leg_event_ids": [
                        leg_a.candidate.event_id,
                        leg_b.candidate.event_id,
                    ],
                }
            ),
        )

    def _upsert_pick(
        self,
        p: ScoredCandidate,
        run_id: int,
        pending_by_key: dict[tuple[str, str, str, str], list[YetAIBet]],
    ) -> None:
        key = self._candidate_pick_key(p.candidate)
        existing = pending_by_key.get(key, [])
        if existing:
            primary = min(
                existing,
                key=lambda b: b.created_at or datetime.min,
            )
            self._apply_pick_fields(primary, p, run_id)
            for dup in existing:
                if dup.id != primary.id:
                    dup.status = "rejected"
                    dup.result = clamp_yetai_result("Superseded by newer auto-pick run")
            log.info("auto_pick refreshed pending pick %s (key=%s)", primary.id, key)
            return

        bet = self._build_bet(p, run_id)
        self.db.add(bet)
        pending_by_key.setdefault(key, []).append(bet)

    def _apply_pick_fields(
        self, bet: YetAIBet, p: ScoredCandidate, run_id: int
    ) -> None:
        """Update an existing pending row in place (preserves id and created_at)."""
        fresh = self._build_bet(p, run_id)
        for field in (
            "title",
            "description",
            "bet_type",
            "selection",
            "odds",
            "confidence",
            "status",
            "source",
            "tier_requirement",
            "confidence_score",
            "score_breakdown",
            "reasoning",
            "auto_pick_run_id",
            "sport",
            "home_team",
            "away_team",
            "commence_time",
            "prediction_factors",
        ):
            setattr(bet, field, getattr(fresh, field))

    def _build_bet(self, p: ScoredCandidate, run_id: int) -> YetAIBet:
        """
        Map a ScoredCandidate onto a YetAIBet row.

        Column notes (verified against database_models.py):
          - id:               String(255) primary key — generate UUID
          - title:            String(255) nullable=False — construct from candidate
          - bet_type:         Enum(BetType) — map from MarketType
          - selection:        String(255) nullable=False — from candidate
          - odds:             Float nullable=False — candidate.market_odds (int -> float)
          - confidence:       Float nullable=False — legacy 0-100 field, use score.total
          - status:           String(50) — set literal "pending_approval" (not enum)
          - source:           Enum(BetSource) — BetSource.AUTO
          - tier_requirement: Enum(SubscriptionTier) — from selector tier assignment
          - confidence_score: Float nullable=True — score.total
          - score_breakdown:  JSONB nullable=True — score.breakdown
          - reasoning:        Text nullable=True — score.reasoning
          - auto_pick_run_id: ForeignKey nullable=True — run_id
          - sport:            String(100) — candidate.league
          - prediction_factors: JSON — store market_line + projection for transparency
        """
        c = p.candidate
        s = p.score
        bet_type = _MARKET_TYPE_TO_BET_TYPE.get(c.market_type, BetType.PROP)

        title = display_matchup_title(c)
        reasoning_text = s.reasoning or ""

        return YetAIBet(
            id=str(uuid.uuid4()),
            # Required non-nullable fields
            title=title,
            description=reasoning_text,
            bet_type=bet_type,
            selection=c.selection,
            odds=float(c.market_odds),
            confidence=s.total,  # legacy 0-100 field
            # Status/source (status is String(50), not enum)
            status="pending_approval",
            source=BetSource.AUTO,
            # Tier assigned by selector
            tier_requirement=p.tier,
            # Auto-pick scoring fields
            confidence_score=s.total,
            score_breakdown=s.breakdown,
            reasoning=reasoning_text,
            auto_pick_run_id=run_id,
            # Game/market context
            sport=c.league,
            home_team=c.home_team,
            away_team=c.away_team,
            commence_time=c.commence_time,
            prediction_factors=_json_safe(
                {
                    "market_line": c.market_line,
                    "our_projection": c.our_projection,
                    "projection_metadata": c.projection_metadata,
                    "event_id": c.event_id,
                }
            ),
        )
