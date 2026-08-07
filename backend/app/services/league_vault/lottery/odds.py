"""
Classic NBA draft lottery odds (ping-pong / combination era).

Uses the 1994–2018 weighting (worst team 25.0% for the top pick, 1 000
combinations). Top three picks are drawn by weighted random without
replacement; remaining lottery teams keep reverse-standings order.
"""

from __future__ import annotations

import secrets
from typing import Any, Sequence, TypeVar

# Combinations out of 1000 for the 14 non-playoff teams (worst → best).
# Source: NBA lottery 1994–2018 (pre-flattening reform).
CLASSIC_NBA_COMBINATIONS: tuple[int, ...] = (
    250,
    199,
    156,
    119,
    88,
    63,
    43,
    28,
    17,
    11,
    8,
    7,
    6,
    5,
)

LOTTERY_PICKS = 3  # classic system drew picks 1–3

T = TypeVar("T")


def combinations_for_field(n: int) -> list[int]:
    """Scale classic 14-team table to ``n`` lottery teams; sum stays 1000."""
    if n <= 0:
        return []
    if n <= len(CLASSIC_NBA_COMBINATIONS):
        raw = list(CLASSIC_NBA_COMBINATIONS[:n])
    else:
        raw = list(CLASSIC_NBA_COMBINATIONS)
        next_odds = CLASSIC_NBA_COMBINATIONS[-1]
        while len(raw) < n:
            next_odds = max(1, next_odds - 1)
            raw.append(next_odds)
    total = sum(raw)
    scaled = [max(1, int(round(x * 1000 / total))) for x in raw]
    # Fix rounding so combinations sum exactly to 1000
    drift = 1000 - sum(scaled)
    scaled[0] = max(1, scaled[0] + drift)
    return scaled


def odds_pct(combinations: Sequence[int]) -> list[float]:
    total = sum(combinations) or 1
    return [round(100.0 * c / total, 1) for c in combinations]


def draw_weighted_order(
    entries_worst_first: Sequence[T],
    combinations: Sequence[int],
    *,
    lottery_picks: int = LOTTERY_PICKS,
    rng: Any = None,
) -> list[T]:
    """
    Draw ``lottery_picks`` winners by weighted chance, then append the rest
    in original (worst-first) order — matching classic NBA lottery mechanics.
    """
    if not entries_worst_first:
        return []
    if len(entries_worst_first) != len(combinations):
        raise ValueError("entries and combinations length mismatch")

    if rng is None:
        rng = secrets.SystemRandom()
    remaining: list[tuple[T, int]] = list(zip(entries_worst_first, combinations))
    drawn: list[T] = []
    n_draw = min(lottery_picks, len(remaining))

    for _ in range(n_draw):
        total = sum(c for _, c in remaining)
        pick = rng.randrange(total)
        cursor = 0
        chosen_idx = len(remaining) - 1
        for i, (_, combos) in enumerate(remaining):
            cursor += combos
            if pick < cursor:
                chosen_idx = i
                break
        entry, _ = remaining.pop(chosen_idx)
        drawn.append(entry)

    drawn.extend(entry for entry, _ in remaining)
    return drawn
