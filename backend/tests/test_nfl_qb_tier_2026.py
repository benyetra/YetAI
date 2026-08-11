"""Hygiene checks for 2026 QB tier table coverage."""

from __future__ import annotations

from app.services.etl.nfl.qb_tiers import (
    lookup_tier_base_yards,
    predict_qb_passing_yards,
)


def test_2026_starters_are_named_tiers():
    """Known 2026 starters should not fall through to the 210 default."""
    named = {
        "Josh Allen": 285,
        "Patrick Mahomes": 280,
        "Jaxson Dart": 210,
        "Cam Ward": 200,
        "Tyler Shough": 195,
        "Michael Penix Jr.": 235,
        "Bo Nix": 245,
        "Drake Maye": 245,
        "Shedeur Sanders": 190,
        "Malik Willis": 205,
        "Kirk Cousins": 235,
        "Aaron Rodgers": 230,
        "Geno Smith": 245,
    }
    for name, expected_base in named.items():
        assert lookup_tier_base_yards(name) == expected_base
        pred = predict_qb_passing_yards(name, 2026, 1, is_backup=False)
        assert pred["prediction_method"] == "dynamic_starter"
        assert 150 <= pred["predicted_passing_yards"] <= 350


def test_penix_jr_normalizes_to_named_tier():
    assert lookup_tier_base_yards("Michael Penix Jr.") == 235
    assert lookup_tier_base_yards("Michael Penix") == 235


def test_unknown_qb_gets_default_base():
    assert lookup_tier_base_yards("Totally Fake QB") == 210
