"""Matchup helper edge cases used by strikeout retrain."""


def test_matchup_adjusted_strikeouts_none_batter_is_neutral():
    from app.services.etl.mlb.mlb_matchup_analysis import matchup_adjusted_strikeouts

    assert matchup_adjusted_strikeouts(12345, None) == 1.0
