"""Tests for batter archetype cold-start priors (Phase 6)."""

from app.services.etl.mlb.profiles.archetypes import (
    ARCHETYPE_PRIORS,
    archetype_batter_profile,
    classify_archetype_from_whiff,
)


def test_classify_power_rhb():
    whiff = {"FF": 0.30, "SL": 0.32}
    assert classify_archetype_from_whiff(whiff, "R") == "power_rhb"


def test_classify_contact_lhb():
    whiff = {"FF": 0.16, "SL": 0.20}
    assert classify_archetype_from_whiff(whiff, "L") == "contact_lhb"


def test_archetype_profile_has_whiff_tensor():
    prof = archetype_batter_profile("power_rhb")
    assert prof["whiff_by_pitch"]["FF"] == ARCHETYPE_PRIORS["power_rhb"]["FF"]
    assert prof["_archetype_id"] == "power_rhb"
