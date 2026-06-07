"""Tests for start/sit team resolution (YetAI-ojg.6)."""

from app.services.start_sit_service import (
    filter_leagues_for_start_sit,
    find_user_team_in_standings,
    resolve_platform_user_id,
)


def test_find_user_team_matches_owner_id():
    standings = [
        {"owner_id": "111", "name": "Other Team"},
        {"owner_id": "222", "name": "My Team"},
    ]
    team = find_user_team_in_standings(standings, "222")
    assert team is not None
    assert team["name"] == "My Team"


def test_find_user_team_does_not_fallback_to_first_team():
    standings = [
        {"owner_id": "111", "name": "Other Team"},
        {"owner_id": "222", "name": "Another Team"},
    ]
    assert find_user_team_in_standings(standings, "999") is None


def test_filter_leagues_returns_all_when_no_filter():
    leagues = [
        {"league_id": "a", "name": "League A"},
        {"league_id": "b", "name": "League B"},
    ]
    assert len(filter_leagues_for_start_sit(leagues)) == 2


def test_filter_leagues_returns_single_match():
    leagues = [
        {"league_id": "a", "name": "League A"},
        {"league_id": "b", "name": "League B"},
    ]
    filtered = filter_leagues_for_start_sit(leagues, "b")
    assert len(filtered) == 1
    assert filtered[0]["name"] == "League B"


def test_filter_leagues_supports_id_field():
    leagues = [{"id": "xyz", "name": "League X"}]
    filtered = filter_leagues_for_start_sit(leagues, "xyz")
    assert len(filtered) == 1


def test_resolve_platform_user_id_from_league_payload():
    assert resolve_platform_user_id({"platform_user_id": "12345"}) == "12345"
    assert resolve_platform_user_id({}) is None
