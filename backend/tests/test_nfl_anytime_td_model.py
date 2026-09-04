import math

from app.services.etl.nfl.anytime_td_model import (
    RB_TD_DISPERSION,
    anytime_td_probability,
    expected_tds,
)


def test_zero_lambda_zero_prob():
    assert anytime_td_probability(0.0) == 0.0


def test_probability_increases_with_lambda():
    assert anytime_td_probability(0.3) < anytime_td_probability(0.8)


def test_expected_tds_multiplicative():
    lam = expected_tds(
        team_rz_trips=3.0,
        player_rz_share=0.25,
        conversion_rate=0.4,
        defense_mult=1.1,
        weather_mult=1.0,
        script_mult=1.0,
    )
    assert abs(lam - 3.0 * 0.25 * 0.4 * 1.1) < 1e-9


def test_anytime_td_probability_clamped():
    assert anytime_td_probability(-1.0) == 0.0
    assert anytime_td_probability(100.0) == 1.0


def test_rb_gl_share_raises_expected_tds_vs_low_gl_back():
    """RB with higher GL share / conversion should have higher λ."""
    low = expected_tds(
        team_rz_trips=3.2,
        player_rz_share=0.20,
        conversion_rate=0.30,
        defense_mult=1.0,
        weather_mult=1.0,
        script_mult=1.0,
    )
    high = expected_tds(
        team_rz_trips=3.2,
        player_rz_share=0.40,
        conversion_rate=0.50,
        defense_mult=1.0,
        weather_mult=1.0,
        script_mult=1.0,
    )
    assert high > low
    assert anytime_td_probability(high) > anytime_td_probability(low)


def test_poisson_anytime_td_probability():
    assert anytime_td_probability(0.0) == 0.0
    p = anytime_td_probability(0.5)
    assert abs(p - (1.0 - math.exp(-0.5))) < 1e-12


def test_rb_negbin_is_below_poisson_for_same_lambda():
    lam = 0.6
    pois = anytime_td_probability(lam)
    nb = anytime_td_probability(lam, dispersion=RB_TD_DISPERSION)
    assert nb < pois
    assert 0.0 < nb < 1.0
