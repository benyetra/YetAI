from __future__ import annotations


def _clamp_weight(weight: float) -> float:
    if weight <= 0.0:
        return 0.0
    if weight >= 1.0:
        return 1.0
    return weight


def blend(value: float, prior: float, weight: float) -> float:
    """result = (1 - w) * value + w * prior; w clamped to [0, 1]."""
    w = _clamp_weight(weight)
    return (1.0 - w) * value + w * prior


def blend_team_run_rates(
    home_mu: float,
    away_mu: float,
    bpp_home_runs: float | None,
    bpp_away_runs: float | None,
    weight: float,
) -> tuple[float, float, bool]:
    """No-op if weight <= 0 or either prior missing."""
    if weight <= 0 or bpp_home_runs is None or bpp_away_runs is None:
        return home_mu, away_mu, False
    return (
        blend(home_mu, bpp_home_runs, weight),
        blend(away_mu, bpp_away_runs, weight),
        True,
    )


def apply_park_factor_to_runs(
    home_mu: float, away_mu: float, runs_percent: int | None
) -> tuple[float, float]:
    """BPP runsPercent is int vs average (18 => +18%). Scale both by (1 + pct/100)."""
    if runs_percent is None:
        return home_mu, away_mu
    scale = 1.0 + runs_percent / 100.0
    return home_mu * scale, away_mu * scale


def blend_prop_mean(
    our_mean: float, bpp_mean: float | None, weight: float
) -> tuple[float, bool]:
    if weight <= 0 or bpp_mean is None:
        return our_mean, False
    return blend(our_mean, bpp_mean, weight), True


def shrink_with_matchup_rate(
    mean: float,
    matchup_prob_pct: float | None,
    *,
    weight: float,
    typical_pa: float = 4.0,
) -> tuple[float, bool]:
    """matchup_prob_pct like 4.2 (% per PA); expected ~= pct/100 * typical_pa."""
    if weight <= 0 or matchup_prob_pct is None:
        return mean, False
    expected = (matchup_prob_pct / 100.0) * typical_pa
    return blend(mean, expected, weight), True
