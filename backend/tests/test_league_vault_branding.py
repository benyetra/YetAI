"""Branding / display hygiene for League Vault pilot sites."""

from app.services.league_vault.branding import (
    is_placeholder_site_name,
    public_manager_display_name,
    sanitize_site_display_name,
)
from app.services.league_vault.ingest.espn_history import espn_league_name_from_payload


def test_sanitize_heals_quoted_placeholder_to_famiglia():
    assert (
        sanitize_site_display_name('"ESPN League 838295"', slug="league-838295")
        == "The Famiglia League"
    )


def test_sanitize_keeps_real_espn_name():
    assert (
        sanitize_site_display_name("The Famiglia League", slug="league-838295")
        == "The Famiglia League"
    )


def test_sanitize_mikes_hard_keeps_good_name():
    assert (
        sanitize_site_display_name("Mike's Hard Fantasy Football", slug="mikes-hard")
        == "Mike's Hard Fantasy Football"
    )


def test_placeholder_detection():
    assert is_placeholder_site_name("ESPN League 838295")
    assert is_placeholder_site_name('"ESPN League 838295"')
    assert not is_placeholder_site_name("The Famiglia League")


def test_espn_league_name_from_payload():
    assert (
        espn_league_name_from_payload({"settings": {"name": "The Famiglia League"}})
        == "The Famiglia League"
    )
    assert espn_league_name_from_payload({"settings": {}}) is None
    assert espn_league_name_from_payload({}) is None


def test_public_manager_collapses_email():
    assert public_manager_display_name("sub2jr@yahoo.com") == "sub2jr"
    assert public_manager_display_name("Rico R") == "Rico R"
