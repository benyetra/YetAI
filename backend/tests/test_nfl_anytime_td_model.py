from app.services.etl.nfl.anytime_td_model import anytime_td_probability, expected_tds


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
