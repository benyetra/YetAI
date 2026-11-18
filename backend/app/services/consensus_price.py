"""Best price and no-vig consensus for game lines and NFL / NHL props, read from the odds
snapshots the ETL's own Odds API fetches already record (no extra credits).

For one side of one market (spread, total, moneyline, or one player's prop) of one event:
- quotes: each book's latest snapshot observation, kept only if it was seen in the last
  ``MAX_QUOTE_AGE`` and its book updated within ``QUOTE_MAX_LAG`` of the freshest book;
- best: among bettable books (never reference-only or consensus-only books) quoting the side
  at a line where our projection is still on that side, the quote with the highest EV at
  the fair probability of the OTHER books quoting EXACTLY the same line (de-vigged per book,
  log-pooled; at least ``MIN_OTHER_BOOKS`` of them). A book at another line is never
  converted: these markets have no validated line conversion (the count-distribution one in
  fair_price/lines.py is for NBA props), so a price never travels with another line.
- no consensus (no fresh quotes, a refused or failed capture, fewer than 3 other books at the
  line) -> every field None, so the candidate is dropped with ``no_consensus_price``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Iterable, Optional

from app.services import odds_math
from app.services.fair_price import consensus, devig, flags

# A quote last seen longer ago than this is not the market now (= the fair-price rule's
# FlagRule.max_age_min); a refused capture leaves only older quotes.
MAX_QUOTE_AGE = timedelta(minutes=30)
# A book whose market update is this far behind the freshest book's is a stale outlier
# (same rule as the NBA prop quotes, _fanduel_lines.QUOTE_MAX_LAG).
QUOTE_MAX_LAG = timedelta(minutes=30)
# The fair-price rule's min_books: the consensus needs this many OTHER books at the line.
MIN_OTHER_BOOKS = 3

FIELDS = ("book", "line", "price", "side", "fair_prob", "ev", "quoted_at")


def _quote(r) -> Optional[flags.Q]:
    """Snapshot row -> two-way quote: 'o' is the over (totals, props) or the home team
    (spreads: line = the home point; moneylines: line 0)."""
    if r.market == "h2h":
        return flags.Q(r.book, 0.0, r.home_price, r.away_price, r.last_seen_at)
    if r.market == "spreads":
        return flags.Q(r.book, r.line, r.home_price, r.away_price, r.last_seen_at)
    return flags.Q(r.book, r.line, r.over_price, r.under_price, r.last_seen_at)


def snapshot_quotes(
    db, *, event_id: str, market: str, player: Optional[str] = None, at: datetime
) -> list[flags.Q]:
    """Each book's latest observation at ``at`` for one event and market (and player:
    exact normalised name, else first initial + surname when only one player matches).
    """
    from app.models.predictions_models import OddsLineSnapshot as S
    from app.services import odds_snapshots

    if not event_id:
        return []
    rows = (
        db.query(S)
        .filter(S.event_id == str(event_id), S.market == market, S.first_seen_at <= at)
        .all()
    )
    if player is not None:
        key = odds_snapshots.player_key(player)
        exact = [r for r in rows if r.player_key == key]
        if not exact and key:
            short = odds_snapshots.short_player_key(player)
            names = {
                r.player_key
                for r in rows
                if odds_snapshots.short_player_key(r.player_key) == short
            }
            exact = [r for r in rows if len(names) == 1 and r.player_key in names]
        rows = exact
    else:
        rows = [r for r in rows if not r.player_key]
    rows = odds_snapshots.rows_at(rows, at)
    updated = [r.book_updated_at for r in rows if r.book_updated_at is not None]
    newest = max(updated, default=None)
    out = []
    for r in rows:
        if at - r.last_seen_at > MAX_QUOTE_AGE:
            continue
        if (
            newest is not None
            and r.book_updated_at is not None
            and newest - r.book_updated_at > QUOTE_MAX_LAG
        ):
            continue
        q = _quote(r)
        if q.line is not None:
            out.append(q)
    return out


def best_same_line(
    quotes: Iterable[flags.Q],
    side: str,
    *,
    on_side: Optional[Callable[[float], bool]] = None,
    min_other_books: int = MIN_OTHER_BOOKS,
) -> Optional[tuple[odds_math.BestQuote, datetime]]:
    """(best quote for ``side`` 'o'/'u', oldest observation it rests on), or None.

    Pure: ``quotes`` are already the fresh ones. Ties: higher price, then FanDuel, then
    book key (as odds_math.best_quote)."""
    rule = flags.default_rule()
    # FAIR_PRICE_EXCLUDED_BOOKS are out of the consensus too, as in the fair-price rule.
    quotes = [q for q in quotes if q.book not in rule.excluded_books]
    skip = rule.reference_only | rule.consensus_only
    fair: dict[str, dict[float, tuple[float, datetime]]] = {}
    for q in quotes:
        two = devig.two_way(q.over_price, q.under_price, rule.method)
        if two is not None:
            fair.setdefault(q.book, {})[float(q.line)] = (two[0], q.last_seen_at)
    best = None
    for q in quotes:
        price = q.over_price if side == "o" else q.under_price
        if q.book in skip or not price:
            continue
        if on_side is not None and not on_side(float(q.line)):
            continue
        others = {
            b: by_line[float(q.line)]
            for b, by_line in fair.items()
            if b != q.book and float(q.line) in by_line
        }
        if len(others) < min_other_books:
            continue
        p_over = consensus.blend({b: p for b, (p, _) in others.items()}, None)
        p = p_over if side == "o" else 1 - p_over
        ev = p * odds_math.american_to_decimal(price) - 1
        rank = (
            ev,
            odds_math.american_to_decimal(price),
            q.book == "fanduel",
            tuple(-ord(c) for c in q.book) + (1,),
        )
        if best is None or rank > best[0]:
            seen = min([q.last_seen_at] + [t for _, t in others.values()])
            bq = odds_math.BestQuote(q.book, float(q.line), int(price), p, ev)
            best = (rank, bq, seen)
    return (best[1], best[2]) if best else None


def same_line_fair(
    rows: Iterable, line: float, min_books: int = MIN_OTHER_BOOKS
) -> Optional[float]:
    """Pooled no-vig P(over) from the books quoting EXACTLY ``line`` (de-vigged per book, then
    blended as in best_same_line); None under ``min_books`` such books. Rows need book, line,
    over_price, under_price. No other line is ever converted."""
    rule = flags.default_rule()
    fair = {}
    for r in rows:
        if r.line is None or float(r.line) != float(line):
            continue
        if r.book in rule.excluded_books:
            continue
        two = devig.two_way(r.over_price, r.under_price, rule.method)
        if two is not None:
            fair[r.book] = two[0]
    return consensus.blend(fair, None) if len(fair) >= min_books else None


def best_fields(
    db,
    *,
    event_id: Optional[str],
    market: str,
    side: Optional[str],
    side_name: Optional[str] = None,
    on_side: Optional[Callable[[float], bool]] = None,
    player: Optional[str] = None,
    prefix: str = "best_",
    with_line: bool = True,
    now: Optional[datetime] = None,
) -> dict:
    """Column values ``{prefix}book ... {prefix}quoted_at`` for a projection row.

    ``side`` 'o' (over / home) or 'u' (under / away); ``side_name`` is what is stored in
    ``{prefix}side``. ``on_side(line)`` gets the quote's line as stored in the snapshot
    (spreads: the home point) and says whether the projection is still on ``side`` there. Always returns every column: None when there is no consensus, so a
    rerun whose capture was refused never leaves an old price looking current. Never
    raises (a failed read is no consensus)."""
    names = [f for f in FIELDS if with_line or f != "line"]
    out = dict.fromkeys((prefix + f for f in names), None)
    if side not in ("o", "u") or not event_id:
        return out
    at = now or datetime.utcnow()
    try:
        # Savepoint: on Postgres a failed read would abort the writer's transaction.
        with db.begin_nested():
            quotes = snapshot_quotes(
                db, event_id=event_id, market=market, player=player, at=at
            )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "consensus_price: snapshot read failed for %s %s", event_id, market
        )
        return out
    found = best_same_line(quotes, side, on_side=on_side)
    if found is None:
        return out
    bq, seen = found
    vals = {
        "book": bq.book,
        # spreads: the side's own line (the away team gets the negated home point)
        "line": -bq.line if market == "spreads" and side == "u" else bq.line,
        "price": bq.price,
        "side": side_name or side,
        "fair_prob": bq.fair_prob,
        "ev": bq.ev,
        "quoted_at": seen,
    }
    return {prefix + f: vals[f] for f in names}
