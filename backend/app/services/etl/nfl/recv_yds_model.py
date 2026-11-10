"""Non-ML receiving-yards model + soft-anchor publish (QB #162 pattern)."""

from __future__ import annotations

import os

DEFAULT_RECV_ANCHOR_ALPHA = 0.25


def recv_anchor_alpha() -> float:
    """Model weight α in soft-anchor publish: ``α·model + (1−α)·line``."""
    raw = os.getenv("NFL_RECV_ANCHOR_ALPHA", str(DEFAULT_RECV_ANCHOR_ALPHA)).strip()
    try:
        alpha = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_RECV_ANCHOR_ALPHA
    if alpha != alpha:  # NaN
        return DEFAULT_RECV_ANCHOR_ALPHA
    return min(1.0, max(0.0, alpha))


def expected_targets(
    *,
    target_share: float | None,
    team_pass_attempts: float | None,
    snap_pct: float | None = None,
) -> float | None:
    """Honest usage prior. Never invent targets from a market line.

    ``snap_pct`` is reserved for future depth blends; v1 requires share × attempts.
    """
    del snap_pct  # unused in v1; kept for API stability
    if target_share is None or team_pass_attempts is None:
        return None
    share = float(target_share)
    attempts = float(team_pass_attempts)
    if share <= 0 or attempts <= 0:
        return None
    return share * attempts


def model_receiving_yards(
    *,
    expected_targets: float,
    yards_per_target: float,
    depth_adj: float = 1.0,
    pace_adj: float = 1.0,
    matchup_adj: float = 1.0,
) -> float:
    """``targets × yards per target × depth/pace/matchup`` — independent of
    the O/U line.

    Yards per target is ``catch rate × yards per reception``. Multiplying
    targets by yards per *reception* alone counts every incompletion as a
    catch and over-projects by roughly a third for wide receivers.
    """
    return (
        float(expected_targets)
        * float(yards_per_target)
        * float(depth_adj)
        * float(pace_adj)
        * float(matchup_adj)
    )


def soft_anchor_recv_yards(
    *,
    model_yards: float,
    ou_line: float,
    alpha: float | None = None,
) -> float:
    """Blend model toward the market line: ``α·model + (1−α)·line``."""
    a = DEFAULT_RECV_ANCHOR_ALPHA if alpha is None else float(alpha)
    a = min(1.0, max(0.0, a))
    model = float(model_yards)
    line = float(ou_line)
    if a >= 1.0 - 1e-12:
        return round(model, 1)
    if a <= 1e-12:
        return round(line, 1)
    return round(a * model + (1.0 - a) * line, 1)


def published_recv_yards(
    *,
    model_yards: float | None,
    ou_line: float | None,
    line_is_real: bool,
    anchor_alpha: float | None = None,
) -> tuple[float | None, str | None]:
    """Publish soft-anchored yards when both model and a real line exist.

    Never returns the raw market line as the sole projection when model is missing.
    """
    if not line_is_real or ou_line is None or model_yards is None:
        return None, None
    alpha = recv_anchor_alpha() if anchor_alpha is None else float(anchor_alpha)
    return (
        soft_anchor_recv_yards(
            model_yards=float(model_yards),
            ou_line=float(ou_line),
            alpha=alpha,
        ),
        "soft_anchor",
    )
