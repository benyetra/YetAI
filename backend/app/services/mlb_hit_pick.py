"""MLB 1+ hit pick helpers — shared by auto-pick and hits board alignment."""

from __future__ import annotations

MIN_COMBINED_SCORE_FOR_AUTO_PICK = 2.0
DEFAULT_HIT_LINE = 0.5
DEFAULT_HIT_ODDS = -110
# Combined 2-leg parlay must pay better than -125 American (e.g. -124, -110, +264).
MIN_PARLAY_COMBINED_ODDS = -125


def qualifies_for_hit_auto_pick(combined_score: float | None) -> bool:
    """Board hitters at or above the production filter threshold."""
    if combined_score is None:
        return False
    return float(combined_score) >= MIN_COMBINED_SCORE_FOR_AUTO_PICK


def projection_from_combined_score(combined_score: float) -> float:
    """Map hits-board score to an implied over-0.5 expectation for edge scoring."""
    return round(0.5 + max(0.0, float(combined_score) - 2.0) * 0.15, 3)


def hit_confidence_pct(combined_score: float) -> float:
    """0–100 confidence from hits-board combined score."""
    if combined_score < MIN_COMBINED_SCORE_FOR_AUTO_PICK:
        return 0.0
    return round(min(100.0, 55.0 + (float(combined_score) - 2.0) * 7.5), 1)
