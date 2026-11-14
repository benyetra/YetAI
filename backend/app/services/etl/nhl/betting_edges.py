"""
Shared DraftKings line vs model edge helpers for NHL daily_predictions.

Shadow calls only. The backtest (scripts/nhl_backtest_2026.py, 2026-27 as-of) found
no edge threshold whose hit rate clears 52.4% with a Wilson interval for the
production formulas: shots (K=10 rate) 53.3% at any edge (n=471, lower bound 0.488),
51.4% at edge >= 0.5 (n=109, 0.421); totals every threshold below 50%; goalie saves
has no stored lines to test. The thresholds below are therefore not pick
thresholds: they decide which rows carry a shadow call to grade. The stored calls build the graded record
that the auto-pick gate and the board read; the board shows no label until that
record qualifies. The backtest supports no MEDIUM/HIGH tier, so edge_category is
always None.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SAVES_CALL_EDGE = 1.5
SHOTS_CALL_EDGE = 0.5
TOTALS_CALL_EDGE = 0.25


@dataclass(frozen=True)
class EdgeResult:
    recommendation: str
    edge_category: Optional[str]
    edge_value: Optional[float]


def _call_diff(diff: float, line: float, threshold: float) -> EdgeResult:
    if diff >= threshold:
        return EdgeResult(f"OVER {line}", None, diff)
    if diff <= -threshold:
        return EdgeResult(f"UNDER {line}", None, diff)
    return EdgeResult("PASS", None, diff)


def _call(predicted: float, line: Optional[float], threshold: float) -> EdgeResult:
    if line is None:
        return EdgeResult("PASS", None, None)
    return _call_diff(predicted - line, line, threshold)


def recommendation_for_saves(predicted: float, line: Optional[float]) -> EdgeResult:
    """Goalie saves O/U."""
    return _call(predicted, line, SAVES_CALL_EDGE)


def recommendation_for_shots(predicted: float, line: Optional[float]) -> EdgeResult:
    """Player SOG O/U."""
    return _call(predicted, line, SHOTS_CALL_EDGE)


def recommendation_for_total_goals(
    predicted_total: float,
    market_line: Optional[float],
    edge: Optional[float] = None,
) -> EdgeResult:
    """Game totals O/U using sportsbook line when available."""
    if market_line is None:
        return EdgeResult("PASS", None, edge)
    diff = edge if edge is not None else predicted_total - market_line
    return _call_diff(diff, market_line, TOTALS_CALL_EDGE)
