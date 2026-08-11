"""Tests for anytime-TD snap / route aggregation (offline)."""

from __future__ import annotations

from app.services.etl.nfl.anytime_td_snaps import (
    aggregate_player_snaps,
    merge_snaps_into_usage,
    normalize_offense_pct,
    route_participation_from_snaps,
)


def test_normalize_offense_pct_fraction_and_percent():
    assert normalize_offense_pct(0.72) == 0.72
    assert abs(normalize_offense_pct(72.0) - 0.72) < 1e-9
    assert normalize_offense_pct(None) is None


def test_aggregate_player_snaps_prior_weeks_only():
    snaps = [
        {
            "player_id": "wr1",
            "week": 1,
            "offense_pct": 0.8,
            "offense_snaps": 50,
            "position": "WR",
        },
        {
            "player_id": "wr1",
            "week": 2,
            "offense_pct": 0.9,
            "offense_snaps": 55,
            "position": "WR",
        },
        {
            "player_id": "wr1",
            "week": 3,
            "offense_pct": 0.1,
            "offense_snaps": 5,
            "position": "WR",
        },
    ]
    out = aggregate_player_snaps(snaps, as_of_week=3)
    assert "wr1" in out
    assert abs(out["wr1"]["snap_pct"] - 0.85) < 1e-9
    assert abs(out["wr1"]["offense_snaps_l3"] - 52.5) < 1e-9


def test_route_participation_uses_snaps_for_pass_catchers():
    assert (
        abs(route_participation_from_snaps("WR", 0.8, team_pass_rate=0.6) - 0.8) < 1e-9
    )
    # RB routes are discounted by pass rate * snap share
    rb = route_participation_from_snaps("RB", 0.6, team_pass_rate=0.55)
    assert 0.0 < rb < 0.6


def test_merge_snaps_into_usage_prefers_real_snaps_over_target_share():
    usage = {
        "wr1": {
            "player_id": "wr1",
            "position": "WR",
            "snap_pct": 0.25,  # target_share proxy
            "targets_l3": 8.0,
        }
    }
    snaps = {
        "wr1": {
            "snap_pct": 0.88,
            "offense_snaps_l3": 54.0,
            "route_participation": 0.88,
            "routes_l3": 32.0,
        }
    }
    merged = merge_snaps_into_usage(usage, snaps)
    assert abs(merged["wr1"]["snap_pct"] - 0.88) < 1e-9
    assert abs(merged["wr1"]["routes_l3"] - 32.0) < 1e-9
    assert abs(merged["wr1"]["route_participation"] - 0.88) < 1e-9
