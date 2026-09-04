"""Anytime-TD probability from expected TD rate λ (Poisson or NegBin)."""

from __future__ import annotations

import math

RB_TD_DISPERSION = 2.0


def expected_tds(
    *,
    team_rz_trips: float,
    player_rz_share: float,
    conversion_rate: float,
    defense_mult: float,
    weather_mult: float,
    script_mult: float,
) -> float:
    return (
        team_rz_trips
        * player_rz_share
        * conversion_rate
        * defense_mult
        * weather_mult
        * script_mult
    )


def anytime_td_probability(
    expected_tds: float, *, dispersion: float | None = None
) -> float:
    lam = max(0.0, float(expected_tds))
    if dispersion is not None and dispersion > 0:
        r = float(dispersion)
        prob = 1.0 - (r / (r + lam)) ** r
    else:
        prob = 1.0 - math.exp(-lam)
    return min(1.0, max(0.0, prob))
