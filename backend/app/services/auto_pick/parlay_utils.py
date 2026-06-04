"""American odds helpers for auto-pick parlay construction."""


def american_to_decimal(odds: int) -> float:
    if odds > 0:
        return (odds / 100.0) + 1.0
    return (100.0 / abs(odds)) + 1.0


def decimal_to_american(decimal_odds: float) -> int:
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1.0) * 100.0))
    return int(round(-100.0 / (decimal_odds - 1.0)))


def combine_parlay_odds(leg_odds: list[int]) -> int:
    combined = 1.0
    for odds in leg_odds:
        combined *= american_to_decimal(odds)
    return decimal_to_american(combined)


def meets_parlay_odds_target(combined_odds: int, min_floor: int = -125) -> bool:
    """True when combined American odds are better than ``min_floor`` (e.g. > -125)."""
    return combined_odds > min_floor
