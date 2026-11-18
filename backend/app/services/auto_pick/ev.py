"""Expected value of a candidate at its real price (pure, no I/O).

A pick is a bet, so it is ranked by what it is expected to return at the price we publish:
EV = p * decimal(price) - 1 per 1u stake.

p starts from the market's own fair (no-vig) probability of the side and adds only a small,
shrunk share of the model's disagreement with the line:
- over/under props: the model's mean is moved toward the line, mean = line + k * (projection -
  line), and its part is P(side | that mean, the stat's market spread) - 0.5 (the line itself is
  the market's coin flip). p = fair + that part.
- moneylines: p = fair + k * (model win prob - fair).
- anything else (spreads, totals): no probability model here, so the candidate is dropped.

The fair probability is the line-shopping consensus that ``odds_math.best_quote`` computes
(stored next to the best price on the NBA prop tables), or the no-vig split of the two prices of
one book when the candidate carries the other side's price. A candidate with neither is dropped:
no probability is made up for a market that has no two-sided price.

Hard gates: the consensus EV at the pick price must be >= 0 (we are not paying more than the
market's own fair price) and the blended EV must exceed MIN_EV.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services import odds_math

# Bump when the rule below changes: the record gate starts a new bet record per version.
SELECTION_VERSION = "ev-v1"

# Smallest blended EV (units per 1u) a pick must beat. Small but above zero, because p is an
# estimate: a candidate within a point or two of fair is noise, not value.
MIN_EV = 0.02

# Share of the model's gap to the line that is trusted (mean = line + k * gap).
# Evidence (docs/reviews/2026-11-17): the NBA points edge has a fitted slope of about 0.10
# (register NBA-4), and every NBA prop model is worse than the line on lined holdout rows
# (points 5.34 vs 4.97 MAE, rebounds 2.03 vs 1.97, assists 1.76 vs 1.71). No stat has evidence
# of more signal than points, so 0.10 is the default. PRA sums three projections' errors and
# has never been measured, so it gets half.
DEFAULT_K = 0.10
PROP_K: dict[str, float] = {"pra": 0.05}
MONEYLINE_K = 0.10

# Canonical candidate stat -> odds_math.MARKET_SD key (the spread best_quote prices with).
STAT_MARKET: dict[str, str] = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "threes": "player_threes",
    "pra": "player_points_rebounds_assists",
    "steals": "player_steals",
    "blocks": "player_blocks",
    "shots": "player_shots_on_goal",
    "shots_on_goal": "player_shots_on_goal",
    "saves": "player_total_saves",
    "passing_yards": "player_pass_yds",
    "receiving_yards": "player_reception_yds",
}

_P_MIN, _P_MAX = 0.01, 0.99


@dataclass(frozen=True)
class EV:
    fair_prob: float  # market consensus fair probability of the side
    model_part: float  # shrunk model share added to fair_prob
    prob: float  # blended probability of the side
    consensus_ev: float  # EV at the pick price at the market's fair probability
    ev: float  # EV at the pick price at the blended probability


def stat_sd(stat: Optional[str]) -> Optional[float]:
    """The stat's market spread, or None when the codebase has none for it."""
    market = STAT_MARKET.get(stat or "")
    return odds_math.MARKET_SD.get(market) if market else None


def prop_model_part(
    stat: str, side: str, projection: float, line: float
) -> Optional[float]:
    """P(side | mean = line + k * (projection - line)) - 0.5, or None without a spread."""
    sd = stat_sd(stat)
    if sd is None:
        return None
    k = PROP_K.get(stat, DEFAULT_K)
    s = "o" if side in ("over", "o") else "u"
    mean = float(line) + k * (float(projection) - float(line))
    return odds_math.prob_side(s, float(line), mean, sd) - 0.5


def _ev(fair: float, part: float, price: float) -> EV:
    dec = odds_math.american_to_decimal(price)
    p = min(_P_MAX, max(_P_MIN, fair + part))
    return EV(
        fair_prob=fair,
        model_part=part,
        prob=p,
        consensus_ev=fair * dec - 1,
        ev=p * dec - 1,
    )


def prop_ev(
    stat: str,
    side: str,
    projection: float,
    line: float,
    price: float,
    fair_prob: Optional[float],
) -> Optional[EV]:
    """EV of an over/under prop at ``price``; None when fair_prob or the spread is missing."""
    if fair_prob is None or not price:
        return None
    part = prop_model_part(stat, side, projection, line)
    if part is None:
        return None
    return _ev(float(fair_prob), part, price)


def gate_reason(e: Optional[EV]) -> Optional[str]:
    """The EV hard gates: why this EV cannot be picked, or None."""
    if e is None:
        return "no_probability"
    if e.consensus_ev < 0:
        return "negative_consensus_ev"
    if e.ev <= MIN_EV:
        return "ev_below_threshold"
    return None


def candidate_ev(c) -> tuple[Optional[EV], Optional[str]]:
    """(EV, None) or (None / EV, drop reason) for a BetCandidate."""
    from app.services.auto_pick.candidate import MarketType

    md = c.projection_metadata
    fair = md.get("fair_prob")
    opp = md.get("opp_odds")
    if fair is None and opp:
        # One book's two prices: its no-vig split. Its EV at its own price is below 0 (the vig),
        # so this only ever passes when a consensus fair_prob is attached instead.
        own = odds_math.american_to_prob(c.market_odds)
        fair = own / (own + odds_math.american_to_prob(opp))
    if fair is None:
        return None, "no_consensus_price"
    if c.market_type == MarketType.PLAYER_PROP:
        e = prop_ev(
            md.get("stat"),
            md.get("side") or "",
            c.our_projection,
            c.market_line,
            c.market_odds,
            fair,
        )
    elif c.market_type == MarketType.MONEYLINE:
        e = _ev(
            float(fair), MONEYLINE_K * (float(c.our_projection) - fair), c.market_odds
        )
    else:
        e = None
    if e is None:
        return None, "no_model_probability"
    return e, gate_reason(e)
