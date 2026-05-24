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
from app.services.auto_pick.selector import BetSelector, ScoredCandidate, SelectorConfig

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
    away = candidate.away_team
    home = candidate.home_team
    if away and home:
        if " vs " in away or " vs " in home:
            return f"{away} vs {home}"
        return f"{away} @ {home}"
    md = candidate.projection_metadata
    team = md.get("team")
    opponent = md.get("opponent")
    if team and opponent:
        return f"{team} vs {opponent}"
    return candidate.selection


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

        selector = BetSelector(
            SelectorConfig(
                threshold=cfg.score_threshold,
                odds_min=cfg.odds_min,
                odds_max=cfg.odds_max,
                max_picks=cfg.max_picks,
            )
        )

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

        status = self._compute_status(
            n_picks=len(picks),
            fails=provider_failures,
            n_providers=len(self.providers),
        )

        run = AutoPickRun(
            run_at=self.now,
            status=status,
            candidates_considered=len(all_candidates),
            candidates_selected=len(picks),
            dropped_reasons={
                sc.candidate.event_id: sc.drop_reason for sc in scored if sc.drop_reason
            },
            error=None,
        )
        self.db.add(run)
        self.db.flush()  # populates run.id

        for p in picks:
            self.db.add(self._build_bet(p, run.id))

        self.db.commit()
        log.info("auto_pick run %s: %s picks, status=%s", run.id, len(picks), status)
        return OrchestratorResult(id=run.id, status=status, pick_count=len(picks))

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
