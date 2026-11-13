"""
AutoPickOrchestrator: coordinates candidate collection, scoring, selection,
and persistence for automated bet picks.
"""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.database_models import (
    AutoPickRun,
    AutoPickRunStatus,
    BetSource,
    BetType,
    YetAIBet,
)
from app.services.auto_pick.candidate import (
    EASTERN,
    EVENING_RUN_ET,
    BetCandidate,
    DateRange,
    MarketType,
    slate_window,
    to_naive_utc,
)
from app.services.auto_pick.config_loader import load_scoring_config
from app.services.auto_pick.context_builder import build_scoring_context
from app.services.auto_pick.scorer import ConfidenceScorer
from app.services.auto_pick.parlay_selector import ParlaySelector, ScoredParlayPick
from app.services.auto_pick.selector import (
    BetSelector,
    ScoredCandidate,
    SelectorConfig,
    game_key,
    hard_gate_reason,
)
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


def _env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() == "true"


DEFAULT_MIN_SCORE = 55.0
# pg_advisory_xact_lock key serialising auto-pick write paths ("YETAIPCK").
AUTO_PICK_LOCK_KEY = 0x5945544149504B


def _min_score() -> float:
    raw = os.getenv("AUTO_YETAI_PICKS_MIN_SCORE")
    if raw is None or not raw.strip():
        return DEFAULT_MIN_SCORE
    try:
        return float(raw)
    except ValueError:
        log.warning(
            "AUTO_YETAI_PICKS_MIN_SCORE=%r is not a number; using %s",
            raw,
            DEFAULT_MIN_SCORE,
        )
        return DEFAULT_MIN_SCORE


def _dialect_name(db: Session) -> str:
    return db.get_bind().dialect.name


def acquire_run_lock(db: Session) -> None:
    """Serialise concurrent runs until this transaction commits (Postgres only)."""
    if _dialect_name(db) != "postgresql":
        return
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUTO_PICK_LOCK_KEY})


def _can_grade(league: str, market: str, stat: Optional[str]) -> bool:
    # Lazy import: a missing grader fails the run loudly instead of skipping the gate.
    from app.services.yetai_grading import can_grade

    return can_grade(league, market, stat)


def grading_block(c: BetCandidate) -> dict:
    """``prediction_factors["grading"]`` per .factory/CONTRACT.md."""
    md = c.projection_metadata
    block = {
        "market": c.market_type.value,
        "league": c.league,
        "game_date": c.game_date.isoformat() if c.game_date else None,
        "home_team": c.home_team,
        "away_team": c.away_team,
        "side": md.get("side"),
        "line": None if c.market_type == MarketType.MONEYLINE else c.market_line,
    }
    if c.market_type == MarketType.PLAYER_PROP:
        block["player"] = md.get("player")
        block["stat"] = md.get("stat")
    return block


def row_market_key(bet: YetAIBet) -> tuple:
    """Same identity as ``market_key`` for an existing row."""
    pf = bet.prediction_factors if isinstance(bet.prediction_factors, dict) else {}
    g = pf.get("grading") or {}
    if g.get("league") and g.get("market"):
        return (g["league"], g["market"])
    market = _BET_TYPE_TO_MARKET.get(bet.bet_type)
    return (bet.sport, market.value if market else None)


def row_game_key(bet: YetAIBet) -> tuple:
    """Same identity as ``game_key`` for an existing row."""
    pf = bet.prediction_factors if isinstance(bet.prediction_factors, dict) else {}
    g = pf.get("grading") or {}
    if g.get("game_date") and g.get("home_team") and g.get("away_team"):
        return (g.get("league"), str(g["game_date"]), g["home_team"], g["away_team"])
    return ("event", str(pf.get("event_id") or ""))


# Map auto-pick MarketType -> YetAIBet BetType enum
_MARKET_TYPE_TO_BET_TYPE: dict[MarketType, BetType] = {
    MarketType.MONEYLINE: BetType.MONEYLINE,
    MarketType.SPREAD: BetType.SPREAD,
    MarketType.TOTAL: BetType.TOTAL,
    MarketType.PLAYER_PROP: BetType.PROP,
}

_BET_TYPE_TO_MARKET = {v: k for k, v in _MARKET_TYPE_TO_BET_TYPE.items()}

_MARKET_TYPE_TO_LEG_BET_TYPE: dict[MarketType, str] = {
    MarketType.MONEYLINE: "Moneyline",
    MarketType.SPREAD: "Spread",
    MarketType.TOTAL: "Total",
    MarketType.PLAYER_PROP: "Player Prop",
}

AUTO_PARLAY_STRATEGY = "auto_2leg"


def parlay_sport_label(legs: tuple[ScoredCandidate, ScoredCandidate]) -> str:
    leagues = {leg.candidate.league for leg in legs if leg.candidate.league}
    if len(leagues) == 1:
        return next(iter(leagues))
    return "Multi-Sport"


@dataclass
class OrchestratorResult:
    id: Optional[int]
    status: AutoPickRunStatus
    pick_count: int
    # Populated for dry runs (and always cheap): the chosen picks and drop summary.
    picks: list = field(default_factory=list)
    dropped_reasons: dict = field(default_factory=dict)


class AutoPickOrchestrator:
    """
    Coordinates the full auto-pick pipeline:
      1. Load scoring config from DB (or defaults).
      2. Build scoring context (recent history, line movements, etc.).
      3. Fan out to all registered providers in parallel.
      4. Score every candidate with ConfidenceScorer.
      5. Apply hard gates, then BetSelector to rank/tier within today's open slots.
      6. Persist YetAIBet rows (source=AUTO): "active" when auto-publish is on
         (default), "pending_approval" when AUTO_YETAI_PICKS_AUTO_PUBLISH=false.
      7. Write an AutoPickRun audit row.
    ``dry_run`` computes everything and writes nothing.
    """

    def __init__(
        self,
        db: Session,
        providers: list,
        now: datetime,
        scorer: Optional[ConfidenceScorer] = None,
        dry_run: bool = False,
        reserve_slots: int = 0,
    ) -> None:
        self.dry_run = dry_run
        # Slots this run leaves for a later run today (cap - reserve, min 1);
        # a reserving run also skips the fill-to-2-from-floor step.
        self.reserve_slots = max(0, reserve_slots)
        self.db = db
        self.providers = providers
        self.now = now
        self.scorer = scorer or ConfidenceScorer()

    async def run(self) -> OrchestratorResult:
        cfg = load_scoring_config(self.db)
        ctx = build_scoring_context(self.db, cfg, self.now)
        auto_publish = _env_flag("AUTO_YETAI_PICKS_AUTO_PUBLISH", "true")
        parlay_enabled = _env_flag("AUTO_YETAI_PARLAY_ENABLED", "false")

        selector_config = SelectorConfig(
            threshold=cfg.score_threshold,
            odds_min=cfg.odds_min,
            odds_max=cfg.odds_max,
            max_picks=cfg.max_picks,
            min_score=_min_score(),
            parlay_leg_threshold=cfg.parlay_leg_threshold,
            parlay_score_threshold=cfg.parlay_score_threshold,
        )
        selector = BetSelector(selector_config)
        parlay_selector = ParlaySelector(selector_config)

        date_range = slate_window(self.now)

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

        if not self.dry_run:
            # Held until commit: a concurrent run waits here, then sees our rows.
            acquire_run_lock(self.db)
        today_rows = self._load_today_auto_rows(date_range) if auto_publish else []
        published = [
            b for b in today_rows if b.status not in ("rejected", "pending_approval")
        ]
        straight_shown = [b for b in published if b.bet_type != BetType.PARLAY]
        # A pulled (void) row frees its slot but its game stays excluded.
        used_games = {row_game_key(b) for b in straight_shown}
        straight_published = [b for b in straight_shown if b.status != "void"]
        market_counts: dict[tuple, int] = {}
        for b in straight_published:
            mk = row_market_key(b)
            market_counts[mk] = market_counts.get(mk, 0) + 1

        gated: list[ScoredCandidate] = []
        for sc in scored:
            sc.drop_reason = self._gate(sc, selector_config, used_games)
            if sc.drop_reason is None:
                gated.append(sc)

        def pick(reserve: int):
            run_cap = max(1, cfg.max_picks - reserve) if reserve else cfg.max_picks
            if auto_publish:
                already = len(straight_published)
                remaining = max(0, run_cap - already)
            else:
                remaining, already = run_cap, 0
            return selector.select(
                gated,
                remaining=remaining,
                already_published=already,
                used_games=used_games,
                market_counts=market_counts,
                fill_floor=reserve == 0,
            )

        reserve = self.reserve_slots
        picks = pick(reserve)
        if reserve:
            # Keep the slot only if something is left for the evening once this run's own
            # picks are taken; otherwise fill the floor now (the evening could not).
            taken = used_games | {game_key(p.candidate) for p in picks}
            if not self._evening_can_pick(scored, selector_config, taken, date_range):
                picks = pick(0)

        parlay_pick = parlay_selector.select_parlay(gated) if parlay_enabled else None
        if parlay_pick and auto_publish:
            if any(
                b.bet_type == BetType.PARLAY and b.status != "rejected"
                for b in today_rows
            ):
                parlay_pick = None
        total_picks = len(picks) + (1 if parlay_pick else 0)

        status = self._compute_status(
            n_picks=total_picks,
            fails=provider_failures,
            n_providers=len(self.providers),
        )
        dropped = self._summarize_drops(scored)

        if self.dry_run:
            return OrchestratorResult(
                id=None,
                status=status,
                pick_count=total_picks,
                picks=picks,
                dropped_reasons=dropped,
            )

        run = AutoPickRun(
            run_at=self.now,
            status=status,
            candidates_considered=len(all_candidates),
            candidates_selected=total_picks,
            dropped_reasons=dropped,
            error=None,
        )
        self.db.add(run)
        self.db.flush()  # populates run.id

        row_status = "active" if auto_publish else "pending_approval"
        if auto_publish:
            for p in picks:
                self.db.add(self._build_bet(p, run.id, row_status))
            if parlay_pick:
                self.db.add(self._build_parlay_bet(parlay_pick, run.id, row_status))
        else:
            pending_by_key = self._load_pending_auto_index()
            for p in picks:
                self._upsert_pick(p, run.id, pending_by_key)
            if parlay_pick:
                self._upsert_parlay_pick(parlay_pick, run.id, pending_by_key)

        self.db.commit()
        log.info(
            "auto_pick run %s: %s straight + %s parlay, status=%s, mode=%s",
            run.id,
            len(picks),
            1 if parlay_pick else 0,
            status,
            "publish" if auto_publish else "pending",
        )
        return OrchestratorResult(
            id=run.id,
            status=status,
            pick_count=total_picks,
            picks=picks,
            dropped_reasons=dropped,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evening_can_pick(
        self,
        scored: list[ScoredCandidate],
        cfg: SelectorConfig,
        used_games: set,
        date_range: DateRange,
    ) -> bool:
        """True if some candidate would still pass the gates and the score floor at
        the evening run (unknown start times fail the gate after 12:00 ET)."""
        evening = to_naive_utc(
            datetime.combine(date_range.slate_date, EVENING_RUN_ET, tzinfo=EASTERN)
        )
        return any(
            sc.score.total >= cfg.min_score
            and self._gate(sc, cfg, used_games, now=evening) is None
            for sc in scored
        )

    def _gate(
        self,
        sc: ScoredCandidate,
        cfg: SelectorConfig,
        used_games: set,
        now: Optional[datetime] = None,
    ) -> Optional[str]:
        reason = hard_gate_reason(sc, now or self.now, cfg.odds_min, cfg.odds_max)
        if reason:
            return reason
        c = sc.candidate
        stat = (
            c.projection_metadata.get("stat")
            if c.market_type == MarketType.PLAYER_PROP
            else None
        )
        if not _can_grade(c.league, c.market_type.value, stat):
            return "ungradeable"
        if game_key(c) in used_games:
            return "event_already_used"
        return None

    def _load_today_auto_rows(self, date_range: DateRange) -> list[YetAIBet]:
        return (
            self.db.query(YetAIBet)
            .filter(
                YetAIBet.source == BetSource.AUTO,
                YetAIBet.created_at >= date_range.start,
                YetAIBet.created_at < date_range.end,
            )
            .all()
        )

    @staticmethod
    def _summarize_drops(scored: list[ScoredCandidate]) -> dict:
        counts: dict[str, int] = {}
        dropped = [sc for sc in scored if sc.drop_reason]
        for sc in dropped:
            counts[sc.drop_reason] = counts.get(sc.drop_reason, 0) + 1
        dropped.sort(key=lambda s: s.score.total, reverse=True)
        top = [
            {
                "event_id": sc.candidate.event_id,
                "selection": sc.candidate.selection,
                "league": sc.candidate.league,
                "market": sc.candidate.market_type.value,
                "score": sc.score.total,
                "reason": sc.drop_reason,
            }
            for sc in dropped[:15]
        ]
        return {"counts": counts, "top_rejected": top}

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
        key = pending_parlay_key(strategy=AUTO_PARLAY_STRATEGY, sport="Multi-Sport")
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
        leg_bet_type = _MARKET_TYPE_TO_LEG_BET_TYPE.get(c.market_type, "Player Prop")
        return _json_safe(
            {
                "sport": c.league,
                "game": game_label,
                "game_id": c.event_id,
                "home_team": c.home_team,
                "away_team": c.away_team,
                "bet_type": leg_bet_type,
                "market_type": c.market_type.value,
                "pick": c.selection,
                "odds": odds_str,
                "confidence": int(round(leg.score.total)),
                "commence_time": (
                    c.commence_time.isoformat() if c.commence_time else None
                ),
                "reasoning": leg.score.reasoning or "",
                "grading": grading_block(c),
            }
        )

    def _build_parlay_bet(
        self, p: ScoredParlayPick, run_id: int, status: str = "pending_approval"
    ) -> YetAIBet:
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
        sport_label = parlay_sport_label(p.legs)
        title = f"2-Leg Parlay ({combined_str})"
        reasoning_text = s.reasoning or ""

        return YetAIBet(
            id=str(uuid.uuid4()),
            title=title,
            description=reasoning_text,
            bet_type=BetType.PARLAY,
            selection="2-Leg Parlay",
            odds=float(p.combined_odds),
            confidence=s.total,
            status=status,
            source=BetSource.AUTO,
            created_at=self.now,
            tier_requirement=p.tier,
            confidence_score=s.total,
            score_breakdown=s.breakdown,
            reasoning=reasoning_text,
            auto_pick_run_id=run_id,
            sport=sport_label,
            home_team=None,
            away_team=None,
            commence_time=earliest_commence,
            parlay_legs=legs_json,
            prediction_factors=_json_safe(
                {
                    "strategy": AUTO_PARLAY_STRATEGY,
                    "combined_odds": p.combined_odds,
                    "leg_event_ids": [
                        leg_a.candidate.event_id,
                        leg_b.candidate.event_id,
                    ],
                    "leg_market_types": [
                        leg_a.candidate.market_type.value,
                        leg_b.candidate.market_type.value,
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

    def _build_bet(
        self, p: ScoredCandidate, run_id: int, status: str = "pending_approval"
    ) -> YetAIBet:
        """
        Map a ScoredCandidate onto a YetAIBet row.

        Column notes (verified against database_models.py):
          - id:               String(255) primary key — generate UUID
          - title:            String(255) nullable=False — construct from candidate
          - bet_type:         Enum(BetType) — map from MarketType
          - selection:        String(255) nullable=False — from candidate
          - odds:             Float nullable=False — candidate.market_odds (int -> float)
          - confidence:       Float nullable=False — legacy 0-100 field, use score.total
          - status:           String(50) — "active" (auto-publish) or "pending_approval"
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
            status=status,
            source=BetSource.AUTO,
            created_at=self.now,
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
                    "grading": grading_block(c),
                    "slate_date": c.game_date.isoformat() if c.game_date else None,
                }
            ),
        )
