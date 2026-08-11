"""Tests for anytime-TD injury / availability filtering (offline)."""

from __future__ import annotations

from app.services.etl.nfl.anytime_td_availability import (
    UNAVAILABLE_STATUSES,
    availability_multiplier,
    is_unavailable_status,
    latest_injury_status_by_player,
    normalize_injury_status,
    apply_availability_to_universe,
)


def test_normalize_injury_status():
    assert normalize_injury_status("Out") == "Out"
    assert normalize_injury_status("doubtful") == "Doubtful"
    assert normalize_injury_status("Questionable") == "Questionable"
    assert normalize_injury_status("IR") == "Out"
    assert normalize_injury_status("Injured Reserve") == "Out"
    assert normalize_injury_status(None) is None


def test_unavailable_statuses():
    assert is_unavailable_status("Out")
    assert is_unavailable_status("Doubtful")
    assert is_unavailable_status("IR")
    assert not is_unavailable_status("Questionable")
    assert not is_unavailable_status("Healthy")
    assert UNAVAILABLE_STATUSES >= {"Out", "Doubtful"}


def test_availability_multiplier():
    assert availability_multiplier("Out") == 0.0
    assert availability_multiplier("Doubtful") == 0.0
    assert 0.0 < availability_multiplier("Questionable") < 1.0
    assert availability_multiplier(None) == 1.0
    assert availability_multiplier("Healthy") == 1.0


def test_latest_injury_status_prefers_target_week():
    records = [
        {"gsis_id": "p1", "week": 2, "report_status": "Questionable"},
        {"gsis_id": "p1", "week": 3, "report_status": "Out"},
        {"gsis_id": "p2", "week": 3, "report_status": "Doubtful"},
    ]
    by_id = latest_injury_status_by_player(records, week=3)
    assert by_id["p1"] == "Out"
    assert by_id["p2"] == "Doubtful"


def test_apply_availability_drops_out_promotes_backup():
    universe = [
        {
            "player_id": "rb1",
            "player_name": "Starter RB",
            "position": "RB",
            "team_abbr": "KC",
            "depth_team": 1,
            "depth_position": "RB",
        }
    ]
    depth = [
        {
            "gsis_id": "rb1",
            "full_name": "Starter RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 1,
            "depth_position": "RB",
            "week": 3,
        },
        {
            "gsis_id": "rb2",
            "full_name": "Backup RB",
            "position": "RB",
            "club_code": "KC",
            "depth_team": 2,
            "depth_position": "RB",
            "week": 3,
        },
    ]
    injuries = {"rb1": "Out"}
    out = apply_availability_to_universe(
        universe,
        injury_by_player=injuries,
        depth_records=depth,
        week=3,
    )
    ids = {p["player_id"] for p in out}
    assert "rb1" not in ids
    assert "rb2" in ids
    rb2 = next(p for p in out if p["player_id"] == "rb2")
    assert rb2["availability_mult"] == 1.0
    assert rb2.get("injury_status") in (None, "Healthy")


def test_apply_availability_downweights_questionable():
    universe = [
        {
            "player_id": "wr1",
            "player_name": "Star WR",
            "position": "WR",
            "team_abbr": "KC",
            "depth_team": 1,
        }
    ]
    out = apply_availability_to_universe(
        universe,
        injury_by_player={"wr1": "Questionable"},
        depth_records=[],
        week=3,
    )
    assert len(out) == 1
    assert out[0]["injury_status"] == "Questionable"
    assert 0.0 < out[0]["availability_mult"] < 1.0
