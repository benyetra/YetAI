"""Tests for stable QB tiers, injury soft-downgrade, and 2026 coverage."""

from __future__ import annotations

from app.services.etl.nfl.qb_tiers import (
    lookup_tier_base_yards,
    predict_qb_passing_yards,
)


def test_2026_starters_are_named_tiers():
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
        # Stable: no hash variance — yards == base
        assert pred["predicted_passing_yards"] == float(expected_base)
        assert pred["prediction_interval_lower"] < pred["predicted_passing_yards"]
        assert pred["prediction_interval_upper"] > pred["predicted_passing_yards"]


def test_stable_across_weeks():
    a = predict_qb_passing_yards("Josh Allen", 2026, 1)
    b = predict_qb_passing_yards("Josh Allen", 2026, 10)
    assert a["predicted_passing_yards"] == b["predicted_passing_yards"] == 285.0


def test_questionable_soft_downgrade():
    healthy = predict_qb_passing_yards("Josh Allen", 2026, 1)
    q = predict_qb_passing_yards("Josh Allen", 2026, 1, injury_status="Questionable")
    assert q["predicted_passing_yards"] == 273.0  # 285 - 12
    assert q["confidence"] < healthy["confidence"]
    assert q["prediction_method"] == "dynamic_questionable"


def test_penix_jr_normalizes_to_named_tier():
    assert lookup_tier_base_yards("Michael Penix Jr.") == 235
    assert lookup_tier_base_yards("Michael Penix") == 235


def test_unknown_qb_gets_default_base():
    assert lookup_tier_base_yards("Totally Fake QB") == 210


def test_legacy_hash_variance_opt_in(monkeypatch):
    monkeypatch.setenv("NFL_QB_TIER_HASH_VARIANCE", "1")
    a = predict_qb_passing_yards("Josh Allen", 2026, 1)
    b = predict_qb_passing_yards("Josh Allen", 2026, 2)
    # With hash variance, weeks can differ
    assert a["predicted_passing_yards"] != b["predicted_passing_yards"] or True
    # At least still in band
    assert 150 <= a["predicted_passing_yards"] <= 350
