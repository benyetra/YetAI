"""Flag rule: leave-one-out consensus fair price vs each bettable book's quote."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from app.services import odds_math
from app.services.fair_price import consensus, devig, lines


def ev(p: float, price: float) -> float:
    """EV per unit staked: p * decimal_odds - 1."""
    return p * odds_math.american_to_decimal(price) - 1


def playable_to(p: float, min_ev: float) -> int:
    """Worst American price still giving EV >= min_ev at p: dec = (1 + min_ev) / p;
    dec >= 2 -> +ceil(100 (dec - 1)), else -floor(100 / (dec - 1))."""
    dec = (1 + min_ev) / p
    if dec >= 2:
        return math.ceil(round(100 * (dec - 1), 9))
    return -math.floor(round(100 / (dec - 1), 9))


@dataclass(frozen=True)
class FlagRule:
    min_ev: float = 0.05
    min_books: int = 3
    max_age_min: float = 30.0
    playable_min_ev: float = 0.02
    p_range: tuple[float, float] = (0.15, 0.85)
    expiry_min: float = 30.0
    excluded_books: frozenset = frozenset()
    reference_only: frozenset = odds_math.REFERENCE_ONLY_BOOKS
    consensus_only: frozenset = frozenset()  # in the consensus, never a flag candidate
    method: str = devig.DEFAULT_METHOD


def default_rule() -> FlagRule:
    """FlagRule with excluded_books from the FAIR_PRICE_EXCLUDED_BOOKS comma list."""
    raw = os.environ.get("FAIR_PRICE_EXCLUDED_BOOKS", "")
    return FlagRule(
        excluded_books=frozenset(b.strip() for b in raw.split(",") if b.strip()),
        consensus_only=odds_math.consensus_only_books(),
    )


@dataclass
class Q:
    """Minimal quote (OddsLineSnapshot rows duck-type to this)."""

    book: str
    line: float
    over_price: int | None
    under_price: int | None
    last_seen_at: datetime


@dataclass
class Flag:
    book: str
    side: str  # 'o' / 'u'
    line: float
    price: int
    fair_prob: float
    ev: float
    playable_to: int
    n_books: int
    at: datetime
    expires_at: datetime


def _fresh(q, at: datetime, rule: FlagRule) -> bool:
    return (
        q.book not in rule.excluded_books
        and q.line is not None
        and (at - q.last_seen_at) <= timedelta(minutes=rule.max_age_min)
    )


def book_fair(
    quotes: Iterable, at: datetime, rule: FlagRule
) -> dict[str, list[tuple[float, float]]]:
    """Per book, its fresh two-way quotes de-vigged with rule.method -> [(line, p_over)]."""
    out: dict[str, list[tuple[float, float]]] = {}
    for q in quotes:
        if not _fresh(q, at, rule):
            continue
        fair = devig.two_way(q.over_price, q.under_price, rule.method)
        if fair:
            out.setdefault(q.book, []).append((q.line, fair[0]))
    return out


def fair_at_line(
    book_probs: dict[str, list[tuple[float, float]]],
    line: float,
    market: str,
    weights: dict[str, float] | None,
    *,
    exclude: str | None = None,
) -> tuple[float | None, int]:
    """Blend (log pool) of every other book's p_over converted to `line`; each book contributes
    its line closest to `line` (tie: p_over nearest 0.5). Returns (p_over, books used).
    """
    got: dict[str, float] = {}
    for book, pts in book_probs.items():
        if book == exclude or not pts:
            continue
        ln, p = min(pts, key=lambda t: (abs(t[0] - line), abs(t[1] - 0.5)))
        conv = lines.convert(p, ln, line, market)
        if conv is not None:
            got[book] = conv
    if not got:
        return None, 0
    return consensus.blend(got, weights), len(got)


def evaluate_prop(
    quotes: list,
    at: datetime,
    market: str,
    weights: dict[str, float] | None,
    rule: FlagRule,
    commence_time: datetime | None = None,
) -> list[Flag]:
    """Flags for each fresh quote of a bettable book and side whose leave-one-out fair
    probability clears min_books, p_range and min_ev."""
    probs = book_fair(quotes, at, rule)
    expires = at + timedelta(minutes=rule.expiry_min)
    if commence_time is not None:
        expires = min(expires, commence_time)
    flags: list[Flag] = []
    for q in quotes:
        if (
            q.book in rule.reference_only
            or q.book in rule.consensus_only
            or not _fresh(q, at, rule)
        ):
            continue
        fair, n = fair_at_line(probs, q.line, market, weights, exclude=q.book)
        if fair is None or n < rule.min_books:
            continue
        for side, price, p in (
            ("o", q.over_price, fair),
            ("u", q.under_price, 1 - fair),
        ):
            if not price or not rule.p_range[0] <= p <= rule.p_range[1]:
                continue
            e = ev(p, price)
            if e >= rule.min_ev:
                flags.append(
                    Flag(
                        q.book,
                        side,
                        q.line,
                        int(price),
                        p,
                        e,
                        playable_to(p, rule.playable_min_ev),
                        n,
                        at,
                        expires,
                    )
                )
    return flags
