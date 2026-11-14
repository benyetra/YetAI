"""MLB-3 regrade script core on fake rows."""

from types import SimpleNamespace

from scripts.mlb_regrade_spreads import regrade_spreads


def _pair(home, away, spread, pick, stored):
    actual = SimpleNamespace(home_score=home, away_score=away, spread_correct=stored)
    proj = SimpleNamespace(
        market_spread=spread, spread_recommendation=pick, run_line=None
    )
    return actual, proj


def test_regrade_counts_flips_and_is_idempotent():
    pairs = [
        _pair(5, 4, -1.5, "HOME", True),  # buggy True -> correct False (flipped)
        _pair(5, 3, -1.5, "HOME", True),  # already right
        _pair(4, 5, 1.5, "HOME", False),  # buggy False -> True (flipped)
        _pair(5, 3, -2.0, "HOME", True),  # push: True -> None (changed, not flipped)
    ]
    dry = regrade_spreads(pairs, apply=False)
    assert dry == {"changed": 3, "unchanged": 1, "flipped": 2}
    assert pairs[0][0].spread_correct is True  # dry run writes nothing

    assert regrade_spreads(pairs, apply=True) == dry
    assert [a.spread_correct for a, _ in pairs] == [False, True, True, None]
    assert regrade_spreads(pairs, apply=True) == {
        "changed": 0,
        "unchanged": 4,
        "flipped": 0,
    }
