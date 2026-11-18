"""Expected value of a candidate at its real price (pure, no I/O).

A pick is a bet, so it is ranked by what it is expected to return at the price we publish:
EV = p * decimal(price) - 1 per 1u stake.

p starts from the market's own fair (no-vig) probability of the side and adds only a small,
shrunk share of the model's disagreement with the line:
- over/under props: the model's mean is moved toward the line, mean = line + k * (projection -
  line), and its part is P(side | that mean, the stat's market spread) - 0.5 (the line itself is
  the market's coin flip). p = fair + that part.
  Only stats whose market spread was measured (the NBA props) get a model part; NFL and NHL
  props (saves, shots, passing and receiving yards) have only placeholder spreads in
  ``odds_math.MARKET_SD``, so their model part is 0 and p = fair.
- spreads and moneylines with a consensus price (NBA, NFL): the projectors publish
  market + a + k * (model - market) with k fitted near 0 (etl/nba/market_anchor.py); the
  model part uses that same k and the league's fitted margin -> probability logistic
  (``_spread_model.margin_to_win_prob`` scale). Spread: P(cover | mean = market margin +
  k * (model - market)) - 0.5. Moneyline: win prob at that mean minus win prob at the market
  margin. With k = 0 the model adds nothing. The constant ``a`` is not counted.
- totals: no fitted spread of game totals exists in the code, so the model part is 0.
- legacy moneylines with only one book's two prices: p = fair + k * (model - fair).

The fair probability is the line-shopping consensus: ``odds_math.best_quote`` for NBA props,
``consensus_price.best_fields`` (other books at the same line) for game lines and NFL / NHL
props, both stored next to the best price on the row; or the no-vig split of the two prices
of one book when the candidate carries the other side's price. A candidate with neither is
dropped: no probability is made up for a market that has no two-sided price.

Hard gates: the consensus EV at the pick price must be >= 0 (we are not paying more than the
market's own fair price) and the blended EV must exceed MIN_EV.
"""

from __future__ import annotations

import math
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

# Stats whose MARKET_SD is a placeholder, not measured: no model part (p = fair).
NO_MODEL_PART_STATS = frozenset(
    {"saves", "shots", "shots_on_goal", "passing_yards", "receiving_yards"}
)

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
    """P(side | mean = line + k * (projection - line)) - 0.5, or None without a spread
    (0 for a stat whose spread was never measured)."""
    if stat in NO_MODEL_PART_STATS:
        return 0.0
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


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def game_model_part(c) -> float:
    """Model part of p for a spread or moneyline candidate with a consensus price, from the
    metadata the sources set: ``anchor_k``, ``model_margin`` (the raw home margin the anchor
    weighs), ``margin_scale`` (the league's logistic scale) and, for moneylines,
    ``market_margin`` (home margin the spread line implies). 0 when any is missing and for
    totals."""
    from app.services.auto_pick.candidate import MarketType

    md = c.projection_metadata
    k, raw, scale = md.get("anchor_k"), md.get("model_margin"), md.get("margin_scale")
    if None in (k, raw, scale) or not scale:
        return 0.0
    k, raw, scale = float(k), float(raw), float(scale)
    home = (md.get("side") or "") == "home"
    if c.market_type == MarketType.SPREAD:
        # side's view: its margin and the margin its own line asks for (-line)
        r = raw if home else -raw
        return _logistic(k * (r + float(c.market_line)) / scale) - 0.5
    if c.market_type == MarketType.MONEYLINE:
        m = md.get("market_margin")
        if m is None:
            return 0.0
        m = float(m)
        part = _logistic((m + k * (raw - m)) / scale) - _logistic(m / scale)
        return part if home else -part
    return 0.0


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
    consensus = fair is not None
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
    elif consensus and c.market_type in (
        MarketType.SPREAD,
        MarketType.TOTAL,
        MarketType.MONEYLINE,
    ):
        e = (
            _ev(float(fair), game_model_part(c), c.market_odds)
            if c.market_odds
            else None
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
