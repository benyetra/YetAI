"""Market-anchor / shrink layer for NFL anytime TD (Option B / criterion #3).

Hierarchical λ (+ gated GBM) remains ``P_model``. Published board probability
shrinks toward vig-free market fair P when residual signal is weak.
"""

from __future__ import annotations

from typing import Any

# Mild overround haircut when only Yes is available (worse than Yes/No).
YES_ONLY_OVERROUND = 0.05

# Edge / Pick gates vs fair market.
ANYTIME_TD_EDGE_THRESHOLD = 0.05
NEAR_MARKET_EPS = 0.02
MAX_SHRINK_W = 0.9

MODEL_VERSION_MARKET_SUFFIX = "_mkt"


def american_to_implied_prob(odds: int | float) -> float:
    """Convert American odds to implied probability (no vig removal)."""
    o = float(odds)
    if o < 0:
        return abs(o) / (abs(o) + 100.0)
    return 100.0 / (o + 100.0)


def vig_free_fair_prob(
    yes_american: int | float,
    no_american: int | float | None = None,
) -> tuple[float, str]:
    """Return (P_fair, source) from Yes / optional No American prices."""
    p_yes = american_to_implied_prob(yes_american)
    if no_american is None:
        fair = max(0.01, min(0.99, p_yes / (1.0 + YES_ONLY_OVERROUND)))
        return fair, "yes_only_haircut"
    p_no = american_to_implied_prob(no_american)
    total = p_yes + p_no
    if total <= 0:
        fair = max(0.01, min(0.99, p_yes / (1.0 + YES_ONLY_OVERROUND)))
        return fair, "yes_only_haircut"
    return max(0.01, min(0.99, p_yes / total)), "yes_no_vigfree"


def market_anchor_signal_score(features: dict[str, Any] | None) -> float:
    """Explicit residual-signal score in ``[0, 1]`` (higher → trust model more).

    v1 inputs: week / thin form, availability-injury, script extremes, RZ/GL
    sample size, depth≥2 midseason. GBM residual confidence is deferred until
    ``conversion_rate_family=rz_gl`` retrain.
    """
    f = features or {}
    score = 0.0
    try:
        week = int(f.get("week") or 1)
    except (TypeError, ValueError):
        week = 1

    gl = f.get("gl_carries")
    rz = f.get("rz_targets")
    td_l3 = f.get("td_l3")
    thin = week <= 1 or (gl is None and rz is None and td_l3 is None)

    try:
        avail = float(
            f.get("availability_mult")
            if f.get("availability_mult") is not None
            else 1.0
        )
    except (TypeError, ValueError):
        avail = 1.0
    injury = str(f.get("injury_status") or "").strip().lower()
    if avail < 0.95 or injury in {"questionable", "doubtful", "out"}:
        score += 0.35

    try:
        script = float(
            f.get("script_mult") if f.get("script_mult") is not None else 1.0
        )
    except (TypeError, ValueError):
        script = 1.0
    if abs(script - 1.0) >= 0.10:
        score += 0.20

    try:
        if gl is not None and float(gl) >= 3:
            score += 0.15
    except (TypeError, ValueError):
        pass
    try:
        if rz is not None and float(rz) >= 5:
            score += 0.15
    except (TypeError, ValueError):
        pass

    if not thin and week >= 4:
        score += 0.15

    try:
        depth = int(f.get("depth_team") or 1)
    except (TypeError, ValueError):
        depth = 1
    if depth >= 2 and week >= 2 and not thin:
        score += 0.10

    return max(0.0, min(1.0, score))


def shrink_weight(signal: float) -> float:
    """Map signal → weight on ``P_model`` (weak signal ≈ full market anchor)."""
    s = max(0.0, min(1.0, float(signal)))
    # Week-1 / null form (~0) → ~0.05; strong shock (~1) → 0.9.
    return min(MAX_SHRINK_W, 0.05 + 0.85 * s)


def blend_publish_prob(p_fair: float, p_model: float, shrink_w: float) -> float:
    """``P_publish = (1 - w) * P_fair + w * P_model``."""
    w = max(0.0, min(MAX_SHRINK_W, float(shrink_w)))
    pub = (1.0 - w) * float(p_fair) + w * float(p_model)
    return max(0.01, min(0.99, pub))


def american_ev(prob: float, yes_american: int | float) -> float:
    """Decimal EV of a 1-unit Yes wager at American odds given win probability."""
    o = float(yes_american)
    profit = 100.0 / abs(o) if o < 0 else o / 100.0
    p = float(prob)
    return p * profit - (1.0 - p)


def recommendation_for_market_edge(
    edge: float,
    *,
    ev: float,
    threshold: float = ANYTIME_TD_EDGE_THRESHOLD,
) -> str:
    """OVER needs edge ≥ τ and EV > 0; UNDER when edge ≤ −τ; else NO_PLAY."""
    if edge >= threshold and ev > 0:
        return "OVER"
    if edge <= -threshold:
        return "UNDER"
    return "NO_PLAY"


def stamp_market_model_version(base_version: str | None) -> str:
    """Append ``_mkt`` once so board rows are labeled market-anchored."""
    base = (base_version or "hierarchical_v1").strip() or "hierarchical_v1"
    if base.endswith(MODEL_VERSION_MARKET_SUFFIX):
        return base
    # Avoid double-suffix if already market-tagged via prior attach.
    if MODEL_VERSION_MARKET_SUFFIX in base:
        return base
    return f"{base}{MODEL_VERSION_MARKET_SUFFIX}"
