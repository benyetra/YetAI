"""Non-ML receiving-yards model + soft-anchor publish (QB #162 pattern)."""

from __future__ import annotations

import os

DEFAULT_RECV_ANCHOR_ALPHA = 0.25

# Receiving yards are right-skewed (many small games, a few huge ones), so the
# mean sits above the median a book's line is set near. We model a game as a
# gamma with the published projection as its mean. PLACEHOLDER: the
# coefficient of variation (sd / mean) is one fixed number for every player,
# in the range seen for WR/TE/RB yards lines. Ceiling: it ignores that role
# players are noisier than volume WRs; replace with a per-position value fit
# on graded rows once enough exist.
RECV_YARDS_CV = 0.85


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


def p_over(mean_yards: float, line: float, cv: float = RECV_YARDS_CV) -> float:
    """P(receiving yards > ``line``) for a gamma with this mean and CV.

    For a skewed stat this is below 0.5 when the line equals the mean, which
    is why a mean above the line is not by itself a reason to take the over.
    """
    from scipy.stats import gamma

    mean = float(mean_yards)
    if mean <= 0:
        return 0.0
    shape = 1.0 / (cv * cv)
    return float(gamma.sf(float(line), a=shape, scale=mean / shape))
