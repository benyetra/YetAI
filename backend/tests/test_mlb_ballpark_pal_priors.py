from __future__ import annotations

import pytest

from app.services.ballpark_pal.priors import (
    apply_park_factor_to_runs,
    blend,
    blend_prop_mean,
    blend_team_run_rates,
    shrink_with_matchup_rate,
)


def test_blend_weight_zero_returns_value():
    assert blend(5.0, 10.0, 0.0) == pytest.approx(5.0)


def test_blend_weight_one_returns_prior():
    assert blend(5.0, 10.0, 1.0) == pytest.approx(10.0)


def test_blend_interpolates_at_half_weight():
    assert blend(4.0, 8.0, 0.5) == pytest.approx(6.0)


def test_blend_clamps_weight_below_zero():
    assert blend(5.0, 10.0, -0.25) == pytest.approx(5.0)


def test_blend_clamps_weight_above_one():
    assert blend(5.0, 10.0, 1.5) == pytest.approx(10.0)


def test_blend_team_run_rates_no_op_when_weight_zero():
    home, away, applied = blend_team_run_rates(4.5, 3.5, 5.0, 4.0, 0.0)
    assert home == pytest.approx(4.5)
    assert away == pytest.approx(3.5)
    assert applied is False


def test_blend_team_run_rates_full_prior_at_weight_one():
    home, away, applied = blend_team_run_rates(4.0, 3.0, 5.0, 4.0, 1.0)
    assert home == pytest.approx(5.0)
    assert away == pytest.approx(4.0)
    assert applied is True


def test_blend_team_run_rates_no_op_when_home_prior_missing():
    home, away, applied = blend_team_run_rates(4.0, 3.0, None, 4.0, 0.3)
    assert home == pytest.approx(4.0)
    assert away == pytest.approx(3.0)
    assert applied is False


def test_blend_team_run_rates_no_op_when_away_prior_missing():
    home, away, applied = blend_team_run_rates(4.0, 3.0, 5.0, None, 0.3)
    assert home == pytest.approx(4.0)
    assert away == pytest.approx(3.0)
    assert applied is False


def test_blend_team_run_rates_blends_both_sides():
    home, away, applied = blend_team_run_rates(4.0, 3.0, 5.0, 4.0, 0.5)
    assert home == pytest.approx(4.5)
    assert away == pytest.approx(3.5)
    assert applied is True


def test_apply_park_factor_to_runs_scales_both_sides():
    home, away = apply_park_factor_to_runs(4.0, 3.0, 18)
    assert home == pytest.approx(4.72)
    assert away == pytest.approx(3.54)


def test_apply_park_factor_to_runs_no_op_when_missing():
    home, away = apply_park_factor_to_runs(4.0, 3.0, None)
    assert home == pytest.approx(4.0)
    assert away == pytest.approx(3.0)


def test_blend_prop_mean_no_op_when_weight_zero():
    mean, applied = blend_prop_mean(6.2, 7.0, 0.0)
    assert mean == pytest.approx(6.2)
    assert applied is False


def test_blend_prop_mean_full_prior_at_weight_one():
    mean, applied = blend_prop_mean(6.0, 8.0, 1.0)
    assert mean == pytest.approx(8.0)
    assert applied is True


def test_blend_prop_mean_no_op_when_prior_missing():
    mean, applied = blend_prop_mean(6.0, None, 0.25)
    assert mean == pytest.approx(6.0)
    assert applied is False


def test_shrink_with_matchup_rate_blends_toward_expected():
    # 4.2% per PA * 4 PA = 0.168 expected HR
    mean, applied = shrink_with_matchup_rate(0.25, 4.2, weight=0.5, typical_pa=4.0)
    assert mean == pytest.approx(0.209)
    assert applied is True


def test_shrink_with_matchup_rate_no_op_when_prob_missing():
    mean, applied = shrink_with_matchup_rate(0.25, None, weight=0.5)
    assert mean == pytest.approx(0.25)
    assert applied is False


def test_shrink_with_matchup_rate_no_op_when_weight_zero():
    mean, applied = shrink_with_matchup_rate(0.25, 4.2, weight=0.0)
    assert mean == pytest.approx(0.25)
    assert applied is False
