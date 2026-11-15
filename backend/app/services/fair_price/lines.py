"""Count-distribution line conversion.

X is a player's integer stat ~ negative binomial, mean mu, variance phi * mu
(scipy nbinom n = mu / (phi - 1), p = 1 / phi); Poisson when phi <= 1.0001.
"""

from __future__ import annotations

import math
from functools import lru_cache

from scipy.special import betainc, pdtr, pdtrc

# Pooled within-player var/mean, 2025-26 box scores, players with >= 20 games of >= 15 min.
# These are unconditional (they include role changes) and so overstate the dispersion given the
# line; refit from closing lines vs outcomes once the backfill exists.
PHI: dict[str, float] = {
    "player_rebounds": 1.262,
    "player_assists": 1.188,
    "player_points": 2.799,
    "player_threes": 1.134,
    "player_steals": 1.047,
    "player_blocks": 1.078,
    "player_points_rebounds_assists": 2.728,
}
# Largest |target - source| line distance converted; beyond it we refuse.
MAX_SHIFT: dict[str, float] = {
    "player_rebounds": 2.0,
    "player_assists": 2.0,
    "player_threes": 1.0,
    "player_steals": 1.0,
    "player_blocks": 1.0,
    "player_points": 4.0,
    "player_points_rebounds_assists": 5.0,
}


def _cdf_sf(k: float, mu: float, phi: float) -> tuple[float, float]:
    """(P(X <= k), P(X > k)) for integer k via scipy.special (no frozen-dist overhead)."""
    k = int(k)
    if k < 0:
        return 0.0, 1.0
    if phi <= 1.0001:
        return float(pdtr(k, mu)), float(pdtrc(k, mu))
    n, p = mu / (phi - 1), 1 / phi
    return float(betainc(n, k + 1, p)), float(betainc(k + 1, n, 1 - p))


def p_over(line: float, mu: float, phi: float) -> float:
    """P(over wins | not a push). Half line L: P(X > L) = 1 - cdf(floor(L)).
    Integer line L: P(X > L) / (P(X > L) + P(X < L))."""
    if line != math.floor(line):
        return _cdf_sf(math.floor(line), mu, phi)[1]
    over = _cdf_sf(line, mu, phi)[1]
    under = _cdf_sf(line - 1, mu, phi)[0]
    return over / (over + under)


@lru_cache(maxsize=500_000)
def mean_for(line: float, p: float, phi: float) -> float | None:
    """mu in [1e-6, 300] with p_over(line, mu, phi) = p (monotone in mu; bisection to 1e-10).
    None when p is outside [0.02, 0.98] or not bracketed."""
    if not 0.02 <= p <= 0.98:
        return None
    lo, hi = 1e-6, 300.0
    if p_over(line, lo, phi) > p or p_over(line, hi, phi) < p:
        return None
    while hi - lo > 1e-10:
        mid = (lo + hi) / 2
        if p_over(line, mid, phi) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def convert(p: float, line_from: float, line_to: float, market: str) -> float | None:
    """P(over) at line_to implied by P(over) = p at line_from. Same line -> p exactly;
    unknown market, shift > MAX_SHIFT, or unsolvable mean -> None."""
    if market not in PHI or market not in MAX_SHIFT:
        return None
    if line_to == line_from:
        return p
    if abs(line_to - line_from) > MAX_SHIFT[market]:
        return None
    phi = PHI[market]
    mu = mean_for(line_from, p, phi)
    return None if mu is None else p_over(line_to, mu, phi)
