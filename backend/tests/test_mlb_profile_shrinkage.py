from app.services.etl.mlb.profiles.shrinkage import posterior_whiff_rate, reliability


def test_posterior_whiff_shrinks_to_league_when_n_zero():
    mean, rel = posterior_whiff_rate(observed=0.5, n_pitches=0, pitch_type="FF")
    assert rel == 0.0
    assert 0.20 < mean < 0.25


def test_reliability_approaches_one():
    assert reliability(400, k=200) > 0.6
