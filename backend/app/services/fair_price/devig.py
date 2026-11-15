"""De-vig methods. Inputs are implied probabilities pi_i of ONE book's market (n >= 2, S = sum pi_i > 0)."""

from __future__ import annotations

import math
from typing import Callable, Sequence

from app.services.odds_math import american_to_prob


def multiplicative(pis: Sequence[float]) -> list[float]:
    """p_i = pi_i / S."""
    s = sum(pis)
    return [p / s for p in pis]


def additive(pis: Sequence[float]) -> list[float] | None:
    """p_i = pi_i - (S - 1) / n. None if any p_i <= 0."""
    n = len(pis)
    off = (sum(pis) - 1) / n
    out = [p - off for p in pis]
    return None if any(p <= 0 for p in out) else out


def power_exponent(pis: Sequence[float]) -> float:
    """k solving sum(pi_i ** k) = 1, bisection on [0.5, 5] (sum is decreasing in k)."""
    lo, hi = 0.5, 5.0
    while hi - lo > 1e-12:
        mid = (lo + hi) / 2
        if sum(p**mid for p in pis) > 1:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def power(pis: Sequence[float]) -> list[float]:
    """p_i = pi_i ** k with k = power_exponent(pis)."""
    k = power_exponent(pis)
    return [p**k for p in pis]


def shin(pis: Sequence[float]) -> list[float]:
    """Shin (1993): p_i = (sqrt(z^2 + 4 (1 - z) pi_i^2 / S) - z) / (2 (1 - z)), z in [0, 0.5)
    chosen by bisection so sum p_i = 1. For n = 2 this equals additive exactly.
    No overround (S <= 1) falls back to multiplicative."""
    s = sum(pis)

    def probs(z: float) -> list[float]:
        return [
            (math.sqrt(z * z + 4 * (1 - z) * p * p / s) - z) / (2 * (1 - z))
            for p in pis
        ]

    if s <= 1:
        return multiplicative(pis)
    lo, hi = 0.0, 0.5 - 1e-12
    while hi - lo > 1e-14:
        mid = (lo + hi) / 2
        if sum(probs(mid)) > 1:  # sum decreases as z grows
            lo = mid
        else:
            hi = mid
    return probs((lo + hi) / 2)


METHODS: dict[str, Callable[[Sequence[float]], list[float] | None]] = {
    "multiplicative": multiplicative,
    "additive": additive,
    "power": power,
    "shin": shin,
}
DEFAULT_METHOD = "power"


def two_way(
    over_price: float | None, under_price: float | None, method: str = DEFAULT_METHOD
) -> tuple[float, float] | None:
    """De-vigged (p_over, p_under) from American prices; None if a price is missing or the method fails."""
    if not over_price or not under_price:
        return None
    out = METHODS[method]([american_to_prob(over_price), american_to_prob(under_price)])
    return None if out is None else (out[0], out[1])


def one_sided(price: float, k: float) -> float:
    """Fair probability of a quote with no opposite side: pi ** k, k = the same book's power exponent."""
    return american_to_prob(price) ** k
