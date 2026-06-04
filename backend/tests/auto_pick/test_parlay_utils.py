from app.services.auto_pick.parlay_utils import (
    combine_parlay_odds,
    meets_parlay_odds_target,
)


def test_combine_two_minus_110_legs_beats_minus_125_floor():
    combined = combine_parlay_odds([-110, -110])
    assert meets_parlay_odds_target(combined)


def test_combine_minus_135_legs_still_beats_minus_125_floor():
    combined = combine_parlay_odds([-135, -135])
    assert meets_parlay_odds_target(combined)


def test_meets_parlay_odds_target():
    assert meets_parlay_odds_target(-124)
    assert meets_parlay_odds_target(264)
    assert not meets_parlay_odds_target(-125)
    assert not meets_parlay_odds_target(-130)
