from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from app.models.database_models import SubscriptionTier
from app.services.auto_pick.candidate import BetCandidate, utc_to_eastern
from app.services.auto_pick.confidence_score import ConfidenceScore
from app.services.auto_pick.sub_scores import raw_edge

VALID_SIDES = ("home", "away", "over", "under")
START_BUFFER = timedelta(minutes=20)
# Past this ET hour a pick with no known start time is assumed to be underway.
UNKNOWN_START_CUTOFF_HOUR = 12


@dataclass
class ScoredCandidate:
    candidate: BetCandidate
    score: ConfidenceScore
    tier: Optional[SubscriptionTier] = None
    drop_reason: Optional[str] = None


@dataclass
class SelectorConfig:
    threshold: float = 65.0
    odds_min: int = -300
    odds_max: int = 400
    max_picks: int = 3
    # Fill the day up to MIN_PICKS with candidates at or above this floor.
    min_score: float = 55.0
    min_picks: int = 2
    # At most this many of the day's straight picks per league + market type.
    max_per_market: int = 2
    # Parlay legs may qualify below straight-pick threshold; parlay score has its own floor.
    parlay_leg_threshold: float = 55.0
    parlay_score_threshold: float = 55.0


_TIER_BY_RANK = [
    SubscriptionTier.FREE,
    SubscriptionTier.PRO,
    SubscriptionTier.PRO,
    SubscriptionTier.ELITE,
]


def game_key(c: BetCandidate) -> tuple:
    """Event identity = the game, falling back to the provider event id."""
    if c.game_date and c.home_team and c.away_team:
        return (c.league, str(c.game_date), c.home_team, c.away_team)
    return ("event", c.event_id)


def market_key(c: BetCandidate) -> tuple:
    return (c.league, c.market_type.value)


def hard_gate_reason(
    sc: ScoredCandidate, now_utc: datetime, odds_min: int, odds_max: int
) -> Optional[str]:
    """Pure gates that need no DB/grader: stable reason name or None."""
    c = sc.candidate
    side = (c.projection_metadata.get("side") or "").lower()
    if side not in VALID_SIDES:
        return "no_play"
    if raw_edge(c) <= 0:
        return "non_positive_edge"
    if c.market_odds < odds_min or c.market_odds > odds_max:
        return "odds_out_of_bounds"
    if c.projection_metadata.get("injury_flag"):
        return "injury_flag"
    if c.commence_time is not None:
        if c.commence_time <= now_utc + START_BUFFER:
            return "started_or_starting"
    elif utc_to_eastern(now_utc).hour >= UNKNOWN_START_CUTOFF_HOUR:
        return "start_time_unknown"
    return None


class BetSelector:
    def __init__(self, config: SelectorConfig):
        self.config = config

    def select(
        self,
        scored: list[ScoredCandidate],
        *,
        remaining: Optional[int] = None,
        already_published: int = 0,
        used_games: Optional[set] = None,
        market_counts: Optional[dict] = None,
        fill_floor: bool = True,
        key_fn: Callable[[BetCandidate], tuple] = game_key,
    ) -> list[ScoredCandidate]:
        """Rank already-gated candidates and choose today's picks.

        ``remaining`` = open slots under the daily cap; ``already_published`` =
        straight picks already live today (sets tier rank and the fill-to-2 rule);
        ``market_counts`` = today's live picks per ``market_key``; ``fill_floor``
        False skips the fill-to-2-from-floor step (left to a later run).
        """
        cfg = self.config
        if remaining is None:
            remaining = cfg.max_picks
        used = set(used_games or ())
        per_market = dict(market_counts or {})

        def crowded(c: BetCandidate) -> bool:
            return per_market.get(market_key(c), 0) >= cfg.max_per_market

        ranked = sorted(scored, key=lambda s: s.score.total, reverse=True)

        picks: list[ScoredCandidate] = []
        chosen: set[int] = set()

        def take(floor: float, limit: int) -> None:
            for sc in ranked:
                if len(picks) >= limit:
                    return
                if id(sc) in chosen or sc.score.total < floor:
                    continue
                k = key_fn(sc.candidate)
                if k in used or crowded(sc.candidate):
                    continue
                picks.append(sc)
                chosen.add(id(sc))
                used.add(k)
                mk = market_key(sc.candidate)
                per_market[mk] = per_market.get(mk, 0) + 1

        take(cfg.threshold, remaining)
        if fill_floor:
            fill_to = min(remaining, max(0, cfg.min_picks - already_published))
            take(cfg.min_score, fill_to)

        for sc in ranked:
            if id(sc) in chosen:
                continue
            k = key_fn(sc.candidate)
            if sc.score.total < cfg.min_score:
                sc.drop_reason = "below_floor"
            elif sc.score.total < cfg.threshold:
                sc.drop_reason = "below_threshold"
            elif k in used:
                sc.drop_reason = "same_event"
            elif crowded(sc.candidate):
                sc.drop_reason = "market_concentration"
            else:
                sc.drop_reason = "cap_reached"

        for i, p in enumerate(picks):
            p.tier = _TIER_BY_RANK[min(already_published + i, len(_TIER_BY_RANK) - 1)]
        return picks
