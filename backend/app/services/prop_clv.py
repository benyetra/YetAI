"""Closing-line value of a taken prop quote against the closing snapshots (pure)."""

from collections import Counter
from typing import Iterable, Optional

from app.services import odds_math
from app.services.odds_snapshots import to_quotes

# Auto-pick / model-review stat -> Odds API market (NBA).
NBA_STAT_MARKET = {
    "points": "player_points",
    "rebounds": "player_rebounds",
    "assists": "player_assists",
    "threes": "player_threes",
    "three_pt_made": "player_threes",
    "pra": "player_points_rebounds_assists",
    "steals": "player_steals",
    "blocks": "player_blocks",
}


# Markets whose spread around the median is not measured (game lines, NFL / NHL props): CLV
# uses only closing books quoting exactly the quote's own line, never a converted one.
SAME_LINE_MARKETS = frozenset(
    {
        "spreads",
        "totals",
        "h2h",
        "player_pass_yds",
        "player_reception_yds",
        "player_total_saves",
    }
)


class SpreadView:
    """A spreads snapshot row seen as an over/under on the HOME margin: line = the margin the
    home side must beat (minus the home point), over = home price, under = away price. An away
    quote's own line is that same number, so both sides share one stat line."""

    def __init__(self, row):
        self._row = row
        self.line = None if row.line is None else -float(row.line)
        self.over_price = row.home_price
        self.under_price = row.away_price

    def __getattr__(self, name):
        return getattr(self._row, name)


def fair_prob_clv(
    side: str,
    line: float,
    taken_rows: Iterable,
    close_rows: Iterable,
    market: str,
) -> Optional[float]:
    """No-vig close vs no-vig at pick time: the consensus fair probability of ``side`` at the
    taken ``line`` from the close rows minus the same figure from the pick-time rows (+ = the
    market moved our way). Both come from the same books-wide consensus, so the vig is removed
    identically and a market that did not move scores exactly 0. None without a two-way quote
    on either side."""
    sd = odds_math.MARKET_SD.get(market, odds_math.DEFAULT_SD)
    close = odds_math.consensus_center(to_quotes(close_rows), sd)
    taken = odds_math.consensus_center(to_quotes(taken_rows), sd)
    if close is None or taken is None:
        return None
    return odds_math.prob_side(side, line, close, sd) - odds_math.prob_side(
        side, line, taken, sd
    )


def clv_vs_close(
    side: str,
    line: float,
    price: Optional[float],
    book: Optional[str],
    rows: Iterable,
    market: str,
) -> Optional[dict]:
    """CLV of ``side`` ('o'/'u') at ``line``/``price`` vs closing ``rows`` (one observation
    per book). Close = the taken book's own closing line, else the modal closing line.
    Returns None without a usable close."""
    rows = [r for r in rows if r.line is not None]
    if not rows:
        return None
    own = [r for r in rows if r.book == book]
    if own:
        row = min(own, key=lambda r: abs(r.line - line))
    else:
        counts = Counter(r.line for r in rows)
        top = max(counts.values())
        # tie -> the modal line closest to the one we took
        ml = min(
            (ln for ln, n in counts.items() if n == top), key=lambda ln: abs(ln - line)
        )
        row = max(
            (r for r in rows if r.line == ml),
            key=lambda r: (r.over_price if side == "o" else r.under_price) or -(10**6),
        )
    sd = odds_math.MARKET_SD.get(market, odds_math.DEFAULT_SD)
    return {
        "row": row,
        "book": row.book,
        "line": float(row.line),
        "price": row.over_price if side == "o" else row.under_price,
        "line_clv": odds_math.line_clv(side, line, row.line),
        # Close fair probability minus the taken price's vigged implied probability: an EV
        # figure, biased by the vig (about -0.024 at -110), not a like-for-like CLV.
        "prob_clv": (
            odds_math.prob_clv(side, line, price, to_quotes(rows), sd)
            if price
            else None
        ),
        "books": len({r.book for r in rows}),
    }
