"""Expected-value publish rule for the NBA residual model.

STATUS: OFF. Nothing calls this module (a test asserts auto_pick never imports
it). Turning it on needs the prove-in record described in the lead's return.

Pure functions: no DB, no env reads.
"""

import math
from dataclasses import dataclass
from typing import Optional

from app.services.auto_pick.parlay_utils import american_to_decimal

MIN_EV = 0.02
Z = 1.0
KELLY_FRACTION = 0.25
MAX_STAKE = 0.02  # fraction of bankroll


@dataclass(frozen=True)
class Decision:
    side: Optional[str]  # "over" | "under" | None
    p: Optional[float]
    p_conservative: Optional[float]
    price: Optional[float]
    ev: Optional[float]
    ev_conservative: Optional[float]
    stake: float
    reason: str  # "no_price" | "below_threshold" | "bet" | "invalid_input"


def _no_bet(reason: str) -> Decision:
    return Decision(None, None, None, None, None, None, 0.0, reason)


def _valid_price(price: Optional[float]) -> bool:
    return (
        price is not None
        and not math.isnan(price)
        and not (-100 < price < 100)  # also excludes 0
        and not math.isinf(price)
    )


def decide(
    p_over: float,
    over_price: Optional[float],
    under_price: Optional[float],
    *,
    p_se: float,
    calibration_error: float,
    min_ev: float = MIN_EV,
    z: float = Z,
    kelly_fraction: float = KELLY_FRACTION,
    max_stake: float = MAX_STAKE,
) -> Decision:
    nums = (p_over, p_se, calibration_error)
    if any(x is None or math.isnan(x) for x in nums) or not 0.0 <= p_over <= 1.0:
        return _no_bet("invalid_input")
    # A missing price arrives as None or (from pandas) NaN: both mean "no quote".
    prices = {
        k: None if v is None or (isinstance(v, float) and math.isnan(v)) else v
        for k, v in (("over", over_price), ("under", under_price))
    }
    for v in prices.values():
        if v is not None and not _valid_price(v):
            return _no_bet("invalid_input")
    if all(v is None for v in prices.values()):
        return _no_bet("no_price")

    margin = z * p_se + calibration_error
    best = None  # (ev_c, Decision)
    for side, price in prices.items():
        if price is None:
            continue
        p = p_over if side == "over" else 1.0 - p_over
        p_c = min(1.0, max(0.0, p - margin))
        d = american_to_decimal(price)
        ev_c = p_c * d - 1.0
        if ev_c < min_ev:
            continue
        b = d - 1.0
        f_star = (b * p_c - (1.0 - p_c)) / b
        stake = max(0.0, min(kelly_fraction * f_star, max_stake))
        dec = Decision(side, p, p_c, price, p * d - 1.0, ev_c, stake, "bet")
        if best is None or ev_c > best[0]:
            best = (ev_c, dec)
    return best[1] if best else _no_bet("below_threshold")
