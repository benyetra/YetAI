"""Tests for QB yards feature engineering."""

from __future__ import annotations

from app.services.etl.nfl.qb_features import (
    FEATURE_NAMES,
    build_qb_features,
    estimate_opp_pass_allowed_from_weekly,
    form_features_from_prior_yards,
    prior_yards_for_player,
    rolling_mean,
    schedule_is_home,
)


def test_feature_names_include_matchup_form():
    names = set(FEATURE_NAMES)
    assert "tier_yards" in names
    assert "rolling_yards_l3" in names
    assert "opp_pass_yds_allowed" in names
    assert "implied_team_total" in names
    assert "is_home" in names


def test_rolling_mean_window():
    assert rolling_mean([100, 200, 300], window=2) == 250.0
    assert rolling_mean([], window=3) is None


def test_prior_yards_leak_safe():
    history = [
        {
            "qb_player_id": "00-1",
            "qb_player_name": "Josh Allen",
            "season": 2024,
            "week": 1,
            "actual_passing_yards": 280,
        },
        {
            "qb_player_id": "00-1",
            "qb_player_name": "Josh Allen",
            "season": 2024,
            "week": 2,
            "actual_passing_yards": 300,
        },
        {
            "qb_player_id": "00-1",
            "qb_player_name": "Josh Allen",
            "season": 2024,
            "week": 3,
            "actual_passing_yards": 999,
        },
    ]
    prior = prior_yards_for_player(history, player_key="00-1", season=2024, week=3)
    assert prior == [280.0, 300.0]


def test_form_features_fallback_to_tier():
    form = form_features_from_prior_yards([], tier_yards=255.0)
    assert form["rolling_yards_l3"] == 255.0
    assert form["season_avg_yards"] == 255.0


def test_form_features_from_history():
    form = form_features_from_prior_yards([200, 220, 240], tier_yards=255.0)
    assert form["rolling_yards_l3"] == 220.0
    assert form["season_avg_yards"] == 220.0


def test_build_qb_features_merges_context():
    feats = build_qb_features(
        tier_yards=260.0,
        season=2026,
        week=4,
        is_backup=False,
        confidence=0.8,
        context={
            "rolling_yards_l3": 250.0,
            "opp_pass_yds_allowed": 235.0,
            "is_home": 1.0,
            "implied_team_total": 27.5,
            "dome": True,
        },
    )
    assert feats["tier_yards"] == 260.0
    assert feats["rolling_yards_l3"] == 250.0
    assert feats["opp_pass_yds_allowed"] == 235.0
    assert feats["is_home"] == 1.0
    assert feats["implied_team_total"] == 27.5
    assert feats["dome"] == 1.0
    assert len(feats) == len(FEATURE_NAMES)


def test_schedule_is_home():
    assert schedule_is_home("KC", "KC", "BUF") == 1.0
    assert schedule_is_home("BUF", "KC", "BUF") == 0.0
    assert schedule_is_home("KC", None, None) == 0.5


def test_estimate_opp_pass_allowed():
    weekly = [
        {
            "position": "QB",
            "recent_team": "BUF",
            "opponent_team": "KC",
            "season": 2024,
            "week": 1,
            "passing_yards": 310,
        },
        {
            "position": "QB",
            "recent_team": "LAC",
            "opponent_team": "KC",
            "season": 2024,
            "week": 2,
            "passing_yards": 250,
        },
        {
            "position": "QB",
            "recent_team": "DEN",
            "opponent_team": "KC",
            "season": 2024,
            "week": 5,
            "passing_yards": 400,
        },
    ]
    allowed = estimate_opp_pass_allowed_from_weekly(
        weekly, opponent_abbr="KC", season=2024, week=4
    )
    assert allowed == 280.0
