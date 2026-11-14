"""Market anchor for NBA game projections (pure, no DB).

    published = market + a + k * (model - market)

``k`` and ``a`` come from a ridge fit of (actual - market) on (model - market)
over earlier graded games only, so the number moves off the line only as far
as the model's measured record says it should: a model with no information
gets k ~ 0 and publishes the line (never worse than the market), and ``a`` is
the correction fitted on the published number's own error. Because both are
fitted jointly on the raw model, the correction is not counted twice. With no
market line the model is published as is.

Measured on 2026-27 (replay: scripts/nba_game_model_replay.py): the totals and
spread models each lost to the line (MAE gap +2.0 and +0.5 points, n=183) and their
edges had no predictive slope, so k stays near zero until that changes.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple, Optional, Tuple


class Anchor(NamedTuple):
    k: float  # weight on the model's disagreement with the line
    a: float  # constant correction, points
    n: int  # graded games the fit used


NO_ANCHOR = Anchor(0.0, 0.0, 0)


def fit_anchor(
    history: Iterable[Tuple[float, float, float]],
    *,
    window: int,
    k_prior: float,
    a_prior: Optional[float],
    k_max: float = 1.0,
) -> Anchor:
    """Ridge fit on the last ``window`` (model, market, actual) rows, oldest first.

    Minimises sum (y - a - k x)^2 + k_prior * mean(x^2) * k^2 + a_prior * a^2
    with x = model - market, y = actual - market: ``k_prior`` and ``a_prior``
    act like that many games of evidence for k = 0 and a = 0; ``a_prior=None``
    fits no constant (a = 0). k is kept in [0, k_max] (a negative weight would
    bet against our own model)."""
    rows = list(history)[-window:] if window else []
    n = len(rows)
    if not n:
        return NO_ANCHOR
    xs = [m - mk for m, mk, _ in rows]
    ys = [act - mk for _, mk, act in rows]
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    lk = k_prior * sxx / n
    if a_prior is None:
        k = sxy / (sxx + lk) if sxx + lk > 0 else 0.0
        return Anchor(min(max(k, 0.0), k_max), 0.0, n)
    la = a_prior
    # [[sxx + lk, sx], [sx, n + la]] @ [k, a] = [sxy, sy]
    det = (sxx + lk) * (n + la) - sx * sx
    k = (sxy * (n + la) - sx * sy) / det if det > 0 else 0.0
    k = min(max(k, 0.0), k_max)
    a = (sy - k * sx) / (n + la)
    return Anchor(k, a, n)


def anchored(model: float, market: Optional[float], anchor: Anchor) -> float:
    """The number to publish for one game."""
    if market is None:
        return model
    return market + anchor.a + anchor.k * (model - market)
