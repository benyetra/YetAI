"""
Shared DraftKings line vs model edge helpers for NHL daily_predictions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EdgeResult:
    recommendation: str
    edge_category: str
    edge_value: Optional[float]


def recommendation_for_saves(predicted: float, line: Optional[float]) -> EdgeResult:
    """Goalie saves O/U — thresholds match generate_daily_predictions."""
    if line is None:
        return EdgeResult("PASS", "LOW", None)

    diff = predicted - line
    if diff >= 2.5:
        return EdgeResult(f"OVER {line}", "HIGH", diff)
    if diff >= 1.5:
        return EdgeResult(f"OVER {line}", "MEDIUM", diff)
    if diff <= -2.5:
        return EdgeResult(f"UNDER {line}", "HIGH", diff)
    if diff <= -1.5:
        return EdgeResult(f"UNDER {line}", "MEDIUM", diff)
    return EdgeResult("PASS", "LOW", diff)


def recommendation_for_shots(predicted: float, line: Optional[float]) -> EdgeResult:
    """Player SOG — slightly tighter thresholds than goalie saves."""
    if line is None:
        return EdgeResult("PASS", "LOW", None)

    diff = predicted - line
    if diff >= 1.5:
        return EdgeResult(f"OVER {line}", "HIGH", diff)
    if diff >= 0.75:
        return EdgeResult(f"OVER {line}", "MEDIUM", diff)
    if diff <= -1.5:
        return EdgeResult(f"UNDER {line}", "HIGH", diff)
    if diff <= -0.75:
        return EdgeResult(f"UNDER {line}", "MEDIUM", diff)
    return EdgeResult("PASS", "LOW", diff)


def recommendation_for_total_goals(
    predicted_total: float,
    market_line: Optional[float],
    edge: Optional[float] = None,
) -> EdgeResult:
    """Game totals O/U using sportsbook line when available."""
    if market_line is None:
        return EdgeResult("PASS", "LOW", edge)

    diff = edge if edge is not None else (predicted_total - market_line)
    if diff >= 0.5:
        return EdgeResult(f"OVER {market_line}", "HIGH", diff)
    if diff >= 0.25:
        return EdgeResult(f"OVER {market_line}", "MEDIUM", diff)
    if diff <= -0.5:
        return EdgeResult(f"UNDER {market_line}", "HIGH", diff)
    if diff <= -0.25:
        return EdgeResult(f"UNDER {market_line}", "MEDIUM", diff)
    return EdgeResult("PASS", "LOW", diff)
