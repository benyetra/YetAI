"""Strikeout pick helpers — shared by ETL, API, and auto-pick.

YetAI pick (stored in ``fanduel_over_under``) is the side implied by our
projected K vs the FanDuel line. That matches what users expect and what
auto-pick scores (projection vs line on the chosen side).

``ev_over_under`` is the +EV side from the strikeout classifier / NB / juice
stack when the model clears the edge gate; otherwise null.
"""

from __future__ import annotations

from typing import Literal, Optional

PickSide = Literal["over", "under", "push"]
EvFlag = Literal["o", "u", "n"]

MIN_K_EDGE_FOR_AUTO_PICK = 0.75
# |proj - line| at or above this many K → pick_confidence 100 (0–100 scale).
K_EDGE_FOR_FULL_CONFIDENCE = 3.0


def projection_pick_side(
    projected_strikeouts: float | None, fanduel_line: float | None
) -> Optional[PickSide]:
    """Over/under/push from our projected K vs the market line."""
    if projected_strikeouts is None or fanduel_line is None or fanduel_line <= 0:
        return None
    if projected_strikeouts > fanduel_line:
        return "over"
    if projected_strikeouts < fanduel_line:
        return "under"
    return "push"


def ev_pick_from_flag(fanduel_flag: str | None) -> Optional[PickSide]:
    """Map ETL ``fanduel_flag`` (o/u/n) to a pick side, or None for no play."""
    if not fanduel_flag:
        return None
    flag = fanduel_flag.strip().lower()
    if flag == "o":
        return "over"
    if flag == "u":
        return "under"
    return None


def k_edge(projected_strikeouts: float, fanduel_line: float) -> float:
    """Signed K edge (projection minus line)."""
    return float(projected_strikeouts) - float(fanduel_line)


def signed_edge_for_side(
    projected_strikeouts: float, fanduel_line: float, side: str
) -> float:
    """Positive when our projection supports the chosen side."""
    delta = k_edge(projected_strikeouts, fanduel_line)
    side_l = (side or "").strip().lower()
    if side_l == "under":
        return -delta
    return delta


def pick_confidence_pct(
    projected_strikeouts: float,
    fanduel_line: float,
    *,
    prob_over: float | None = None,
    ev_edge_pct: float | None = None,
) -> float:
    """
    0–100 confidence for the YetAI (projection) pick.

    Blends K-edge magnitude with model P(correct side) when available.
    """
    side = projection_pick_side(projected_strikeouts, fanduel_line)
    if side is None or side == "push":
        return 0.0

    edge_mag = abs(k_edge(projected_strikeouts, fanduel_line))
    edge_score = min(100.0, (edge_mag / K_EDGE_FOR_FULL_CONFIDENCE) * 100.0)

    model_score = 50.0
    if prob_over is not None:
        p = float(prob_over) if side == "over" else 1.0 - float(prob_over)
        model_score = max(0.0, min(100.0, p * 100.0))

    blended = 0.65 * edge_score + 0.35 * model_score
    if ev_edge_pct is not None and ev_edge_pct > 0:
        blended = min(100.0, blended + min(15.0, float(ev_edge_pct) * 0.5))
    return round(blended, 1)


def qualifies_for_auto_pick(
    projected_strikeouts: float | None,
    fanduel_line: float | None,
    pick_side: str | None,
) -> bool:
    """Auto-pick only uses rows with a real line and meaningful K edge."""
    if (
        projected_strikeouts is None
        or fanduel_line is None
        or fanduel_line <= 0
        or not pick_side
    ):
        return False
    return abs(k_edge(projected_strikeouts, fanduel_line)) >= MIN_K_EDGE_FOR_AUTO_PICK


def enrich_strikeout_projection_row(
    row: dict,
    *,
    fanduel_flag: str | None = None,
    prob_over: float | None = None,
    pick_edge_pct: float | None = None,
) -> dict:
    """API-facing fields for strikeout projection rows."""
    proj = row.get("projected_strikeouts")
    line = row.get("fanduel_line")
    yetai = projection_pick_side(proj, line)
    ev = ev_pick_from_flag(fanduel_flag)
    out = dict(row)
    out["yetai_pick"] = yetai
    out["ev_pick"] = ev
    if proj is not None and line is not None and line > 0:
        out["k_edge"] = round(k_edge(float(proj), float(line)), 2)
        out["pick_confidence"] = pick_confidence_pct(
            float(proj),
            float(line),
            prob_over=prob_over,
            ev_edge_pct=pick_edge_pct,
        )
        out["pick_aligned_with_ev"] = ev is None or ev == yetai
    else:
        out["k_edge"] = None
        out["pick_confidence"] = None
        out["pick_aligned_with_ev"] = None
    if yetai is not None:
        out["fanduel_over_under"] = yetai
    return out
