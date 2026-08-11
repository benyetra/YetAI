"""Tests for QB feature engineering + defense/injury helpers."""

from __future__ import annotations

from app.services.etl.nfl.qb_features import (
    FEATURE_NAMES,
    build_qb_features,
    encode_scheme_tags,
    estimate_opp_defense_from_weekly,
    estimate_opp_pass_allowed_from_weekly,
    form_features_from_prior_yards,
    injury_risk_from_status,
    prior_yards_for_player,
    rolling_mean,
    schedule_is_home,
)


def test_feature_names_include_matchup_form():
    names = set(FEATURE_NAMES)
    assert "tier_yards" in names
    assert "rolling_yards_l3" in names
    assert "opp_pass_yds_allowed" in names
    assert "opp_def_epa" in names
    assert "opp_pressure_rate" in names
    assert "injury_risk" in names
    assert "implied_team_total" in names
    assert "total_line" in names
    assert "spread_line" in names
    assert "pass_yds_line" in names
    assert "opp_cover_base" in names
    assert "opp_man_zone" in names
    assert "opp_scheme_pressure" in names


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


def test_injury_risk_mapping():
    assert injury_risk_from_status("Healthy") == 0.0
    assert injury_risk_from_status("Questionable") == 0.55
    assert injury_risk_from_status("Out") == 1.0


def test_build_qb_features_merges_context():
    feats = build_qb_features(
        tier_yards=260.0,
        season=2026,
        week=4,
        context={
            "rolling_yards_l3": 250.0,
            "opp_pass_yds_allowed": 235.0,
            "opp_def_epa": 0.08,
            "opp_pressure_rate": 0.3,
            "is_home": 1.0,
            "implied_team_total": 27.5,
            "dome": True,
            "injury_status": "Probable",
        },
    )
    assert feats["opp_def_epa"] == 0.08
    assert feats["injury_risk"] == 0.2
    assert len(feats) == len(FEATURE_NAMES)


def test_schedule_is_home():
    assert schedule_is_home("KC", "KC", "BUF") == 1.0
    assert schedule_is_home("BUF", "KC", "BUF") == 0.0


def test_estimate_opp_defense_from_weekly():
    weekly = [
        {
            "position": "QB",
            "opponent_team": "KC",
            "season": 2024,
            "week": 1,
            "passing_epa": 0.2,
            "attempts": 40,
            "sacks": 4,
        },
        {
            "position": "QB",
            "opponent_team": "KC",
            "season": 2024,
            "week": 2,
            "passing_epa": 0.0,
            "attempts": 30,
            "sacks": 3,
        },
    ]
    out = estimate_opp_defense_from_weekly(
        weekly, opponent_abbr="KC", season=2024, week=4
    )
    assert abs(out["opp_def_epa"] - 0.1) < 1e-9
    assert abs(out["opp_pressure_rate"] - 0.1) < 1e-9


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
    ]
    allowed = estimate_opp_pass_allowed_from_weekly(
        weekly, opponent_abbr="KC", season=2024, week=4
    )
    assert allowed == 280.0


def test_encode_scheme_tags():
    out = encode_scheme_tags(
        {"cover_base": "cover_1", "man_zone_lean": "man", "pressure_lean": "high"}
    )
    assert out["opp_cover_base"] == 1.0
    assert out["opp_man_zone"] == 1.0
    assert out["opp_scheme_pressure"] == 0.75


def test_build_qb_features_market_and_scheme():
    feats = build_qb_features(
        tier_yards=250.0,
        season=2025,
        week=3,
        context={
            "total_line": 48.5,
            "spread_line": -3.0,
            "cover_base": "cover_2",
            "man_zone_lean": "zone",
            "pressure_lean": "high",
        },
    )
    assert feats["total_line"] == 48.5
    assert feats["spread_line"] == -3.0
    assert feats["opp_cover_base"] == 2.0
    assert feats["opp_scheme_pressure"] == 0.75
    assert feats["implied_team_total"] == 25.75  # 48.5/2 - (-3)/2
