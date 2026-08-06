"""Branding / display hygiene for League Vault pilot sites."""

from app.services.league_vault.branding import (
    public_manager_display_name,
    sanitize_site_display_name,
)


def test_sanitize_strips_quoted_espn_name():
    assert (
        sanitize_site_display_name('"ESPN League 838295"', slug="league-838295")
        == "ESPN League 838295"
    )


def test_sanitize_mikes_hard_keeps_good_name():
    assert (
        sanitize_site_display_name("Mike's Hard Fantasy Football", slug="mikes-hard")
        == "Mike's Hard Fantasy Football"
    )


def test_public_manager_collapses_email():
    assert public_manager_display_name("sub2jr@yahoo.com") == "sub2jr"
    assert public_manager_display_name("Rico R") == "Rico R"
