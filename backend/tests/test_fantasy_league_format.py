"""Tests for Sleeper league format trade-value multipliers."""

from app.services.fantasy_league_format import (
    QB_PREMIUM_2QB,
    QB_PREMIUM_SUPERFLEX,
    age_multiplier_for_format,
    format_multiplier,
    is_dynasty_league,
    league_format_flags_from_sleeper,
    league_format_from_sleeper,
)
from app.services.fantasy_trade_value import calculate_deterministic_trade_value


def test_league_format_detects_superflex():
    league = {
        "roster_positions": [
            "QB",
            "RB",
            "RB",
            "WR",
            "WR",
            "TE",
            "FLEX",
            "SUPER_FLEX",
            "BN",
        ],
        "scoring_settings": {"rec": 1},
        "settings": {"num_teams": 12},
    }
    fmt = league_format_from_sleeper(league)
    assert fmt["has_superflex"] is True
    assert fmt["is_2qb"] is False
    assert fmt["qb_premium_multiplier"] == QB_PREMIUM_SUPERFLEX


def test_league_format_detects_2qb_without_superflex():
    league = {
        "roster_positions": ["QB", "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN"],
        "scoring_settings": {"rec": 1},
        "settings": {"num_teams": 10},
    }
    fmt = league_format_from_sleeper(league)
    assert fmt["has_superflex"] is False
    assert fmt["is_2qb"] is True
    assert fmt["qb_premium_multiplier"] == QB_PREMIUM_2QB


def test_league_format_te_premium_and_scarcity():
    league = {
        "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN"],
        "scoring_settings": {"rec": 1, "bonus_rec_te": 0.5},
        "settings": {"num_teams": 12},
    }
    fmt = league_format_from_sleeper(league)
    assert fmt["te_premium"] == 0.5
    assert fmt["te_scarcity_multiplier"] == 1.08


def test_qb_superflex_value_exceeds_standard_league():
    player = {"id": "qb-1", "position": "QB", "age": 27, "team": "KC"}
    standard = calculate_deterministic_trade_value(player, scoring_type="ppr")
    superflex = calculate_deterministic_trade_value(
        player,
        scoring_type="ppr",
        league_format={
            "has_superflex": True,
            "is_2qb": False,
            "qb_premium_multiplier": QB_PREMIUM_SUPERFLEX,
            "te_premium": 0,
            "team_count": 12,
            "te_scarcity_multiplier": 1.05,
        },
    )
    assert superflex > standard
    assert abs(superflex / standard - QB_PREMIUM_SUPERFLEX) < 0.05


def test_format_multiplier_superflex_overrides_2qb():
    league_format = {
        "has_superflex": True,
        "is_2qb": True,
        "qb_premium_multiplier": QB_PREMIUM_SUPERFLEX,
        "te_premium": 0,
        "team_count": 12,
        "te_scarcity_multiplier": 1.05,
    }
    assert format_multiplier("QB", league_format) == QB_PREMIUM_SUPERFLEX


def test_league_format_detects_dynasty_from_sleeper_type():
    dynasty = {"settings": {"type": 2}}
    keeper = {"settings": {"type": 1}}
    redraft = {"settings": {"type": 0}}

    assert league_format_flags_from_sleeper(dynasty)["format_type"] == "dynasty"
    assert is_dynasty_league(dynasty) is True
    assert league_format_flags_from_sleeper(keeper)["format_type"] == "keeper"
    assert league_format_flags_from_sleeper(redraft)["format_type"] == "redraft"

    fmt = league_format_from_sleeper({**dynasty, "roster_positions": ["QB", "RB"]})
    assert fmt["is_dynasty"] is True


def test_dynasty_age_multiplier_favors_youth():
    assert age_multiplier_for_format(22, is_dynasty=True) > age_multiplier_for_format(
        22, is_dynasty=False
    )
    assert age_multiplier_for_format(32, is_dynasty=True) < age_multiplier_for_format(
        32, is_dynasty=False
    )


def test_young_player_higher_value_in_dynasty_league():
    player = {"id": "wr-young", "position": "WR", "age": 22, "team": "DET"}
    redraft = calculate_deterministic_trade_value(player, scoring_type="ppr")
    dynasty = calculate_deterministic_trade_value(
        player,
        scoring_type="ppr",
        league_format={"is_dynasty": True},
    )
    assert dynasty > redraft


def test_te_format_multiplier_includes_premium_and_scarcity():
    league_format = {
        "has_superflex": False,
        "is_2qb": False,
        "qb_premium_multiplier": 1.0,
        "te_premium": 0.5,
        "team_count": 12,
        "te_scarcity_multiplier": 1.08,
    }
    assert format_multiplier("TE", league_format) == 1.58
