"""Unit tests for anytime-TD PBP red-zone aggregators (no network)."""

from __future__ import annotations

from app.services.etl.nfl.anytime_td_features import _player_rz_share_from_usage
from app.services.etl.nfl.anytime_td_pbp import (
    aggregate_player_rz_from_pbp,
    aggregate_team_rz_from_pbp,
    filter_goal_line_plays,
    filter_red_zone_plays,
)


def _pbp_sample() -> list[dict]:
    """Tiny RZ/GL play set — KC offense weeks 1–2."""
    return [
        # Week 1 RZ pass → WR
        {
            "week": 1,
            "posteam": "KC",
            "yardline_100": 15,
            "pass": 1,
            "rush": 0,
            "receiver_player_id": "wr1",
            "rusher_player_id": None,
            "drive": 1,
        },
        {
            "week": 1,
            "posteam": "KC",
            "yardline_100": 12,
            "pass": 1,
            "rush": 0,
            "receiver_player_id": "wr1",
            "rusher_player_id": None,
            "drive": 1,
        },
        # Week 1 RZ rush → RB (also GL)
        {
            "week": 1,
            "posteam": "KC",
            "yardline_100": 3,
            "pass": 0,
            "rush": 1,
            "receiver_player_id": None,
            "rusher_player_id": "rb1",
            "drive": 2,
        },
        # Week 2 RZ
        {
            "week": 2,
            "posteam": "KC",
            "yardline_100": 18,
            "pass": 1,
            "rush": 0,
            "receiver_player_id": "te1",
            "rusher_player_id": None,
            "drive": 1,
        },
        {
            "week": 2,
            "posteam": "KC",
            "yardline_100": 4,
            "pass": 0,
            "rush": 1,
            "receiver_player_id": None,
            "rusher_player_id": "rb1",
            "drive": 2,
        },
        # Outside RZ — ignored
        {
            "week": 1,
            "posteam": "KC",
            "yardline_100": 45,
            "pass": 1,
            "rush": 0,
            "receiver_player_id": "wr1",
            "rusher_player_id": None,
            "drive": 3,
        },
    ]


def test_filter_red_zone_and_goal_line():
    plays = _pbp_sample()
    rz = filter_red_zone_plays(plays)
    gl = filter_goal_line_plays(plays)
    assert len(rz) == 5
    assert len(gl) == 2
    assert all(p["yardline_100"] <= 20 for p in rz)
    assert all(p["yardline_100"] <= 5 for p in gl)


def test_aggregate_team_rz_from_pbp_prior_weeks():
    team = aggregate_team_rz_from_pbp(_pbp_sample(), as_of_week=3)
    assert "KC" in team
    # 2 weeks of RZ activity → trips per game from distinct drives
    assert team["KC"]["team_rz_trips"] > 0
    assert 0.35 <= team["KC"]["team_rz_pass_rate"] <= 0.75


def test_aggregate_player_rz_from_pbp():
    players = aggregate_player_rz_from_pbp(_pbp_sample(), as_of_week=3)
    assert "rb1" in players
    assert players["rb1"]["gl_carries"] >= 1
    assert players["wr1"]["rz_targets"] >= 1
    assert players["wr1"]["player_rz_share"] is not None
    assert 0.0 < players["wr1"]["player_rz_share"] <= 1.0
    assert players["rb1"]["rz_rush_share"] is not None
    assert players["rb1"]["gl_carry_share"] is not None
    assert players["rb1"]["gl_carries_pg"] is not None


def test_aggregate_team_early_down_pass_pct():
    plays = _pbp_sample() + [
        {
            "week": 1,
            "posteam": "KC",
            "yardline_100": 10,
            "pass": 1,
            "rush": 0,
            "down": 1,
            "receiver_player_id": "wr1",
            "rusher_player_id": None,
            "drive": 4,
        },
        {
            "week": 1,
            "posteam": "KC",
            "yardline_100": 8,
            "pass": 0,
            "rush": 1,
            "down": 2,
            "receiver_player_id": None,
            "rusher_player_id": "rb1",
            "drive": 4,
        },
    ]
    team = aggregate_team_rz_from_pbp(plays, as_of_week=3)
    assert 0.30 <= team["KC"]["early_down_pass_pct"] <= 0.70


def test_resolve_position_rz_share_rb_prefers_rush_and_gl():
    from app.services.etl.nfl.anytime_td_pbp import resolve_position_rz_share

    share = resolve_position_rz_share(
        position="RB",
        rz_rush_share=0.40,
        rz_target_share=0.05,
        gl_carry_share=0.50,
        blended_share=0.20,
    )
    assert share is not None
    assert abs(share - (0.70 * 0.40 + 0.30 * 0.50)) < 1e-9


def test_player_rz_share_uses_games_count_key():
    """Regression: usage stores games_count, not game_count."""
    share = _player_rz_share_from_usage(
        {"td_season": 4.0, "games_count": 8},
        {"team_tds_per_game": 2.0},
        "RB",
    )
    assert share is not None
    assert 0.02 <= share <= 0.55
