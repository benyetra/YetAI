"""Tests for pitcher archetype classify / cold-start priors."""

from datetime import date
from unittest.mock import MagicMock

from app.services.etl.mlb.profiles.pitcher_archetypes import (
    archetype_pitcher_profile,
    classify_pitcher_archetype,
    pitcher_snapshot_is_thin,
    resolve_pitcher_profile_for_matchup,
)


def test_classify_power_fastball():
    usage = {"FF": 0.70, "SL": 0.20, "CH": 0.10}
    assert classify_pitcher_archetype(usage, avg_fb_velo=96.0) == "power_fastball"


def test_classify_sinker_groundball():
    usage = {"SI": 0.30, "FF": 0.25, "SL": 0.25, "CH": 0.20}
    assert classify_pitcher_archetype(usage, avg_fb_velo=93.0) == "sinker_groundball"


def test_classify_breaking_ball_heavy():
    usage = {"SL": 0.25, "CU": 0.20, "FF": 0.40, "CH": 0.15}
    assert classify_pitcher_archetype(usage, avg_fb_velo=93.0) == "breaking_ball_heavy"


def test_classify_changeup_specialist():
    usage = {"CH": 0.28, "FF": 0.45, "SL": 0.27}
    assert classify_pitcher_archetype(usage, avg_fb_velo=93.0) == "changeup_specialist"


def test_classify_finesse_control():
    usage = {"FF": 0.62, "CH": 0.15, "CU": 0.13, "SL": 0.10}
    assert classify_pitcher_archetype(usage, avg_fb_velo=90.0) == "finesse_control"


def test_archetype_profile_has_usage_and_velo():
    prof = archetype_pitcher_profile("power_fastball")
    assert abs(sum(prof["usage"].values()) - 1.0) < 0.02
    assert prof["avg_fb_velo"] >= 95
    assert prof["_archetype_id"] == "power_fastball"
    assert "location" in prof


def test_pitcher_snapshot_is_thin():
    assert pitcher_snapshot_is_thin(50, {"FF": 1.0}) is True
    assert pitcher_snapshot_is_thin(300, {"FF": 1.0}) is False
    assert pitcher_snapshot_is_thin(300, {}) is True
    assert pitcher_snapshot_is_thin(None, {"FF": 1.0}) is True


def test_resolve_thick_keeps_observed():
    snap = MagicMock()
    snap.profile = {"usage": {"FF": 0.6, "SL": 0.4}, "location": {}}
    snap.n_pitches = 500
    prof, src = resolve_pitcher_profile_for_matchup(None, 1, snap, date(2024, 6, 1))
    assert src == "observed"
    assert prof["usage"]["FF"] == 0.6


def test_resolve_thin_uses_archetype_prior():
    snap = MagicMock()
    snap.profile = {"usage": {"FF": 1.0}}
    snap.n_pitches = 40
    db = MagicMock()
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.services.etl.mlb.profiles.pitcher_archetypes.get_pitcher_archetype",
        return_value="power_fastball",
    ):
        prof, src = resolve_pitcher_profile_for_matchup(db, 1, snap, date(2024, 6, 1))
    assert src == "archetype"
    assert prof["_archetype_id"] == "power_fastball"
