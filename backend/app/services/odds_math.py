"""American-odds maths shared by grading, line shopping and CLV (pure, no I/O).

Conventions: prices are American odds (-110, +120); probabilities are 0..1; units are profit
per 1u staked (a loss is -1). "over"/"under" sides are written 'o'/'u'.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist, median
from typing import Iterable, Optional

BREAKEVEN_PRICE = -110  # assumed price for a call with no stored price
_N = NormalDist()

# Spread of the stat around its market median, for comparing quotes at different lines and for
# the fair probability at a line the close no longer offers.
# ponytail: one normal sd per market; replace with per-player / Poisson tails if line-shopping
# choices between different lines ever matter more than half a point.
MARKET_SD: dict[str, float] = {
    "player_points": 6.5,
    "player_rebounds": 3.0,
    "player_assists": 2.5,
    "player_threes": 1.4,
    "player_points_rebounds_assists": 8.5,
    "player_steals": 1.0,
    "player_blocks": 1.0,
    "player_shots_on_goal": 1.4,
    "player_total_saves": 6.0,
    "player_pass_yds": 55.0,
    "player_reception_yds": 25.0,
}
DEFAULT_SD = 5.0

# Quoted for the consensus, never offered as the best book (not bettable in the US).
REFERENCE_ONLY_BOOKS = frozenset({"pinnacle"})


def american_to_decimal(price: float) -> float:
    price = float(price)
    return 1 + (price / 100 if price > 0 else 100 / abs(price))


def american_to_prob(price: float) -> float:
    """Implied probability of an American price (vig included)."""
    return 1 / american_to_decimal(price)


def units_won(price: float, won: bool) -> float:
    """Profit per 1u stake at ``price``: +0.909 at -110 when won, -1 when lost."""
    return american_to_decimal(price) - 1 if won else -1.0


def units_for_result(result: str, price: Optional[float]) -> float:
    """Units for a graded row result ('hit'/'miss'; anything else 0) at ``price``
    (``BREAKEVEN_PRICE`` when the row has none)."""
    if result not in ("hit", "miss"):
        return 0.0
    return units_won(price if price else BREAKEVEN_PRICE, result == "hit")


def breakeven_rate(price: float) -> float:
    """Hit rate needed to break even at ``price`` (= its implied probability)."""
    return american_to_prob(price)


def devig(over_price: float, under_price: float) -> tuple[float, float]:
    """Fair (no-vig) over/under probabilities by multiplicative normalisation."""
    po, pu = american_to_prob(over_price), american_to_prob(under_price)
    return po / (po + pu), pu / (po + pu)


def fair_median(line: float, over_price: float, under_price: float, sd: float) -> float:
    """Median of a normal stat whose P(X > line) is the book's fair over probability."""
    p_over = devig(over_price, under_price)[0]
    return float(line) + sd * _N.inv_cdf(p_over)


def prob_side(side: str, line: float, center: float, sd: float) -> float:
    """P(over ``line``) or P(under ``line``) for a normal(center, sd) stat."""
    p_under = _N.cdf((float(line) - center) / sd)
    return 1 - p_under if side == "o" else p_under


@dataclass(frozen=True)
class Quote:
    """One book's two-way quote at one line (either price may be missing)."""

    book: str
    line: Optional[float]
    over_price: Optional[int]
    under_price: Optional[int]

    def price(self, side: str) -> Optional[int]:
        return self.over_price if side == "o" else self.under_price


@dataclass(frozen=True)
class BestQuote:
    book: str
    line: float
    price: int
    fair_prob: Optional[float]  # consensus fair probability of the side at this line
    ev: Optional[float]  # expected units per 1u at that probability


def consensus_center(quotes: Iterable[Quote], sd: float) -> Optional[float]:
    """Median of the books' fair medians (books quoting both sides at a line)."""
    centers = [
        fair_median(q.line, q.over_price, q.under_price, sd)
        for q in quotes
        if q.line is not None and q.over_price and q.under_price
    ]
    return median(centers) if centers else None


def _on_side(side: str, projection: Optional[float], line: float) -> bool:
    if projection is None:
        return True
    # Same rule as pick_side: an under only below the line, everything else an over.
    return (float(projection) < line) == (side == "u")


def best_quote(
    quotes: Iterable[Quote],
    side: str,
    *,
    projection: Optional[float] = None,
    sd: float = DEFAULT_SD,
) -> Optional[BestQuote]:
    """Best bettable (book, line, price) for ``side``.

    Ranked by expected value at the consensus fair probability of ``side`` at each book's own
    line, so a price is only ever compared together with the line it was offered at. With every
    book on one line this is the highest price. Only lines where ``projection`` is still on
    ``side`` qualify. Ties: higher price, then FanDuel, then book key.
    """
    quotes = list(quotes)
    center = consensus_center(quotes, sd)
    best: Optional[tuple] = None
    for q in quotes:
        price = q.price(side)
        if q.book in REFERENCE_ONLY_BOOKS or q.line is None or not price:
            continue
        if not _on_side(side, projection, q.line):
            continue
        fair = prob_side(side, q.line, center, sd) if center is not None else None
        ev = fair * american_to_decimal(price) - 1 if fair is not None else None
        # No consensus (no two-way quote anywhere): better line first, then price.
        line_rank = -q.line if side == "o" else q.line
        rank = (
            ev if ev is not None else line_rank,
            american_to_decimal(price),
            q.book == "fanduel",
            # reversed key order so "a" beats "z" on a full tie
            tuple(-ord(c) for c in q.book),
        )
        if best is None or rank > best[0]:
            best = (rank, BestQuote(q.book, float(q.line), int(price), fair, ev))
    return best[1] if best else None


def line_clv(side: str, taken_line: float, closing_line: float) -> float:
    """Points of line value (+ = the close moved toward us): over Lc - L0, under L0 - Lc."""
    move = float(closing_line) - float(taken_line)
    return move if side == "o" else -move


def prob_clv(
    side: str,
    taken_line: float,
    taken_price: float,
    closing: Iterable[Quote],
    sd: float = DEFAULT_SD,
) -> Optional[float]:
    """Closing consensus fair probability of ``side`` at the line we took, minus the implied
    probability of the price we took (+ = we beat the close). None without a two-way close.
    """
    center = consensus_center(closing, sd)
    if center is None:
        return None
    return prob_side(side, taken_line, center, sd) - american_to_prob(taken_price)
