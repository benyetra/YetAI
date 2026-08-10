"""Tests for NFL anytime-TD feature builders (pure, no network)."""

from __future__ import annotations

import pytest

from app.services.etl.nfl.anytime_td_features import (
    build_player_feature_row,
    defense_multiplier,
    scheme_defense_adjustment,
    weather_multiplier,
)


def test_scheme_defense_adjustment_bounded():
    adj = scheme_defense_adjustment("cover_3", "zone", "medium", "RB")
    assert 0.9 <= adj <= 1.15


def test_scheme_defense_adjustment_position_sensitive():
    man_wr = scheme_defense_adjustment("cover_1", "man", "high", "WR")
    man_rb = scheme_defense_adjustment("cover_1", "man", "high", "RB")
    assert man_wr != man_rb


def test_defense_multiplier_uses_aggregate_and_scheme():
    scheme = {
        "cover_base": "cover_3",
        "man_zone_lean": "zone",
        "pressure_lean": "medium",
    }
    league_avg = 0.5
    mult = defense_multiplier(scheme, tds_allowed_vs_pos=0.75, league_avg=league_avg)
    assert mult > 1.0
    assert 0.85 <= mult <= 1.25


def test_defense_multiplier_falls_back_without_scheme():
    mult = defense_multiplier(None, tds_allowed_vs_pos=0.5, league_avg=0.5)
    assert abs(mult - 1.0) < 1e-9


def test_weather_multiplier_dome_neutral():
    assert weather_multiplier(outdoor=False, wind_mph=None, precip=False) == 1.0


def test_weather_multiplier_wind_and_precip_reduce():
    calm = weather_multiplier(outdoor=True, wind_mph=5.0, precip=False)
    bad = weather_multiplier(outdoor=True, wind_mph=25.0, precip=True)
    assert bad < calm
    assert 0.85 <= bad <= 1.0


def test_build_player_feature_row_projector_keys():
    row = build_player_feature_row(
        player_id="p1",
        player_name="Test Player",
        position="RB",
        team_name="Kansas City Chiefs",
        opponent_team_name="Buffalo Bills",
        season=2025,
        week=5,
    )
    for key in (
        "team_rz_trips",
        "player_rz_share",
        "conversion_rate",
        "defense_mult",
        "weather_mult",
        "script_mult",
    ):
        assert key in row
        assert isinstance(row[key], float)


def test_build_player_feature_row_includes_all_feature_groups():
    row = build_player_feature_row(
        player_id="p1",
        player_name="Test Player",
        position="WR",
        team_name="KC",
        opponent_team_name="BUF",
        season=2025,
        week=5,
        player_stats={
            "snap_pct": 0.85,
            "targets_l3": 8.0,
            "carries_l3": 0.0,
            "routes_l3": 28.0,
            "td_l3": 1.0,
            "td_l5": 2.0,
            "td_season": 4.0,
            "rz_targets": 3.0,
            "gl_carries": 0.0,
            "player_rz_share": 0.22,
            "conversion_rate": 0.28,
        },
        team_stats={
            "team_rz_trips": 3.8,
            "early_down_pass_pct": 0.52,
            "team_rz_pass_rate": 0.58,
        },
        opponent_defense={
            "tds_allowed_vs_pos": 0.62,
            "rz_td_rate_allowed": 0.55,
            "def_epa": 0.04,
        },
        scheme={
            "cover_base": "cover_2",
            "man_zone_lean": "zone",
            "pressure_lean": "high",
        },
        weather={"outdoor": True, "wind_mph": 12.0, "precip": False},
        game_env={"implied_total": 48.5, "spread": -3.0, "implied_team_total": 25.75},
    )
    assert row["snap_pct"] == 0.85
    assert row["targets_l3"] == 8.0
    assert row["team_rz_trips"] == 3.8
    assert row["player_rz_share"] == 0.22
    assert row["conversion_rate"] == 0.28
    assert row["early_down_pass_pct"] == 0.52
    assert row["tds_allowed_vs_pos"] == 0.62
    assert row["cover_base"] == "cover_2"
    assert row["outdoor"] is True
    assert row["implied_total"] == 48.5
    assert row["team_name"] == "Kansas City Chiefs"
    assert row["opponent_team_name"] == "Buffalo Bills"


def test_build_player_feature_row_uses_league_priors_when_missing():
    row = build_player_feature_row(
        player_id="p2",
        player_name="Backup TE",
        position="TE",
        team_name="NE",
        opponent_team_name="MIA",
        season=2025,
        week=1,
    )
    assert row["team_rz_trips"] > 0
    assert 0 < row["player_rz_share"] < 1
    assert 0 < row["conversion_rate"] < 1
    assert row["snap_pct"] is not None
    assert row["tds_allowed_vs_pos"] > 0


def test_build_player_feature_row_script_mult_scales_with_total():
    low = build_player_feature_row(
        player_id="a",
        player_name="A",
        position="RB",
        team_name="KC",
        opponent_team_name="BUF",
        season=2025,
        week=1,
        game_env={"implied_team_total": 18.0},
    )
    high = build_player_feature_row(
        player_id="b",
        player_name="B",
        position="RB",
        team_name="KC",
        opponent_team_name="BUF",
        season=2025,
        week=1,
        game_env={"implied_team_total": 28.0},
    )
    assert high["script_mult"] > low["script_mult"]
