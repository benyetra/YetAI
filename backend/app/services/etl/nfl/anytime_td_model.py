"""Poisson anytime-TD probability from expected TD rate λ."""

from __future__ import annotations

import math


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


def anytime_td_probability(expected_tds: float) -> float:
    lam = max(0.0, expected_tds)
    prob = 1.0 - math.exp(-lam)
    return min(1.0, max(0.0, prob))
