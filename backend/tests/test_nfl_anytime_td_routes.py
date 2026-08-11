"""Tests for anytime-TD true route participation (offline)."""

from __future__ import annotations

from app.services.etl.nfl.anytime_td_routes import (
    aggregate_player_routes,
    merge_routes_into_usage,
    weekly_route_records_from_pass_plays,
)


def test_weekly_routes_count_skill_players_on_pass_plays_only():
    plays = [
        {
            "week": 1,
            "team": "KC",
            "offense_players": "wr1;ol1;qb1;te1;rb1",
        },
        {
            "week": 1,
            "team": "KC",
            "offense_players": "wr1;ol1;qb1;te1",
        },
        {
            "week": 1,
            "team": "KC",
            "offense_players": "wr2;ol1;qb1",
        },
    ]
    positions = {
        "wr1": "WR",
        "wr2": "WR",
        "te1": "TE",
        "rb1": "RB",
        "qb1": "QB",
        "ol1": "T",
    }
    rows = weekly_route_records_from_pass_plays(plays, position_by_player=positions)
    by_id = {r["player_id"]: r for r in rows}
    assert by_id["wr1"]["routes"] == 2.0
    assert by_id["wr1"]["team_dropbacks"] == 3.0
    assert by_id["te1"]["routes"] == 2.0
    assert by_id["rb1"]["routes"] == 1.0
    assert "qb1" not in by_id
    assert "ol1" not in by_id


def test_aggregate_player_routes_prior_weeks_and_participation():
    records = [
        {
            "player_id": "wr1",
            "week": 1,
            "team": "KC",
            "position": "WR",
            "routes": 40,
            "team_dropbacks": 50,
        },
        {
            "player_id": "wr1",
            "week": 2,
            "team": "KC",
            "position": "WR",
            "routes": 50,
            "team_dropbacks": 50,
        },
        {
            "player_id": "wr1",
            "week": 3,
            "team": "KC",
            "position": "WR",
            "routes": 10,
            "team_dropbacks": 50,
        },
    ]
    out = aggregate_player_routes(records, as_of_week=3)
    assert "wr1" in out
    assert abs(out["wr1"]["routes_l3"] - 45.0) < 1e-9
    assert abs(out["wr1"]["route_participation"] - 0.9) < 1e-9
    assert out["wr1"]["routes_source"] == "pbp_participation"
    # Week 3 excluded when as_of_week=3
    assert "wr1" not in aggregate_player_routes(records, as_of_week=1)


def test_merge_routes_overwrites_snap_proxy():
    usage = {
        "wr1": {
            "player_id": "wr1",
            "position": "WR",
            "routes_l3": 30.0,
            "route_participation": 0.8,
            "routes_source": "snap_proxy",
        }
    }
    routes = {
        "wr1": {
            "routes_l3": 42.0,
            "route_participation": 0.91,
            "routes_source": "pbp_participation",
        }
    }
    merged = merge_routes_into_usage(usage, routes)
    assert abs(merged["wr1"]["routes_l3"] - 42.0) < 1e-9
    assert abs(merged["wr1"]["route_participation"] - 0.91) < 1e-9
    assert merged["wr1"]["routes_source"] == "pbp_participation"
