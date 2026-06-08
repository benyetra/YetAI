"""Tests for Sleeper-first fantasy trade recommendations."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.fantasy_trade_recommendations import (
    count_positions,
    generate_sleeper_trade_recommendations,
    identify_position_needs,
    identify_position_surplus,
    partner_complement_score,
    select_complementary_partner,
    value_gap_ratio,
)


def _player(name: str, position: str, trade_value: float = 20.0) -> dict:
    return {
        "id": hash(name) % 10000,
        "player_id": name.replace(" ", "_").lower(),
        "name": name,
        "position": position,
        "team": "KC",
        "age": 26,
        "trade_value": trade_value,
    }


def test_identify_position_needs_and_surplus():
    roster = [
        _player("QB One", "QB"),
        _player("RB One", "RB"),
        _player("RB Two", "RB"),
        _player("WR One", "WR"),
        _player("WR Two", "WR"),
        _player("WR Three", "WR"),
        _player("TE One", "TE"),
    ]
    counts = count_positions(roster)
    assert counts["QB"] == 1
    assert counts["RB"] == 2
    assert counts["WR"] == 3
    assert counts["TE"] == 1

    needs = identify_position_needs(counts)
    surplus = identify_position_surplus(counts)

    assert "QB" in needs
    assert "RB" in needs
    assert "WR" in needs
    assert "TE" in needs
    assert surplus == []


def test_identify_position_surplus_rb_and_wr():
    roster = [
        _player("QB One", "QB"),
        _player("QB Two", "QB"),
        _player("QB Three", "QB"),
        _player("RB One", "RB"),
        _player("RB Two", "RB"),
        _player("RB Three", "RB"),
        _player("RB Four", "RB"),
        _player("RB Five", "RB"),
        _player("WR One", "WR"),
        _player("WR Two", "WR"),
        _player("WR Three", "WR"),
        _player("WR Four", "WR"),
        _player("WR Five", "WR"),
        _player("WR Six", "WR"),
        _player("WR Seven", "WR"),
        _player("TE One", "TE"),
        _player("TE Two", "TE"),
        _player("TE Three", "TE"),
        _player("TE Four", "TE"),
    ]
    counts = count_positions(roster)
    surplus = identify_position_surplus(counts)

    assert "RB" in surplus
    assert "WR" in surplus
    assert "QB" in surplus
    assert "TE" in surplus


def test_partner_complement_score_prefers_matching_profiles():
    user_needs = ["QB", "WR"]
    user_surplus = ["RB"]
    partner_counts = count_positions(
        [
            _player("QB One", "QB"),
            _player("QB Two", "QB"),
            _player("QB Three", "QB"),
            _player("RB One", "RB"),
            _player("WR One", "WR"),
        ]
    )
    strong = partner_complement_score(user_needs, user_surplus, partner_counts)

    weak_partner_counts = count_positions(
        [
            _player("QB One", "QB"),
            _player("RB One", "RB"),
            _player("RB Two", "RB"),
            _player("RB Three", "RB"),
            _player("WR One", "WR"),
            _player("WR Two", "WR"),
            _player("WR Three", "WR"),
            _player("WR Four", "WR"),
        ]
    )
    weak = partner_complement_score(user_needs, user_surplus, weak_partner_counts)

    assert strong > weak


def test_select_complementary_partner_is_stable():
    teams = [
        {"team_id": 2, "name": "Beta"},
        {"team_id": 3, "name": "Gamma"},
    ]
    partner_rosters = {
        2: [
            _player("QB One", "QB"),
            _player("QB Two", "QB"),
            _player("QB Three", "QB"),
            _player("RB One", "RB"),
        ],
        3: [
            _player("QB One", "QB"),
            _player("RB One", "RB"),
            _player("RB Two", "RB"),
            _player("RB Three", "RB"),
            _player("WR One", "WR"),
            _player("WR Two", "WR"),
            _player("WR Three", "WR"),
            _player("WR Four", "WR"),
        ],
    }
    first = select_complementary_partner(
        teams,
        partner_rosters,
        user_needs=["QB"],
        user_surplus=["RB"],
        seed="team-1:need:QB",
    )
    second = select_complementary_partner(
        teams,
        partner_rosters,
        user_needs=["QB"],
        user_surplus=["RB"],
        seed="team-1:need:QB",
    )
    assert first == second
    assert first is not None
    assert first["team_id"] == 2


def test_value_gap_ratio_within_fifteen_percent():
    give = [_player("RB One", "RB", trade_value=30.0)]
    get = [_player("WR One", "WR", trade_value=28.0)]
    assert value_gap_ratio(give, get) <= 0.15


@pytest.mark.asyncio
@patch("app.services.fantasy_trade_recommendations.fetch_team_roster_players")
async def test_generate_sleeper_trade_recommendations_never_empty_we_get(
    mock_fetch_roster,
):
    user_roster = [
        _player("QB One", "QB"),
        _player("RB One", "RB"),
        _player("RB Two", "RB"),
        _player("RB Three", "RB"),
        _player("RB Four", "RB"),
        _player("RB Five", "RB"),
        _player("WR One", "WR"),
        _player("WR Two", "WR"),
        _player("WR Three", "WR"),
        _player("TE One", "TE"),
    ]
    partner_roster = [
        _player("Partner QB", "QB", trade_value=35.0),
        _player("Partner QB2", "QB", trade_value=25.0),
        _player("Partner WR", "WR", trade_value=30.0),
        _player("Partner WR2", "WR", trade_value=22.0),
        _player("Partner WR3", "WR", trade_value=20.0),
        _player("Partner WR4", "WR", trade_value=18.0),
        _player("Partner RB", "RB", trade_value=24.0),
        _player("Partner TE", "TE", trade_value=15.0),
    ]

    async def roster_side_effect(_service, _league_id, team_id, **kwargs):
        if int(team_id) == 1:
            return user_roster
        if int(team_id) == 2:
            return partner_roster
        return []

    mock_fetch_roster.side_effect = roster_side_effect

    sleeper_service = AsyncMock()
    sleeper_service.get_league_teams = AsyncMock(
        return_value=[
            {"team_id": 1, "name": "My Team"},
            {"team_id": 2, "name": "Partner Team"},
        ]
    )

    recommendations = await generate_sleeper_trade_recommendations(
        sleeper_service=sleeper_service,
        league_id="league-1",
        team_id=1,
        scoring_type="ppr",
        max_recommendations=10,
    )

    assert recommendations
    for rec in recommendations:
        assert rec["we_get"]["players"]
        assert all(p.get("name") for p in rec["we_get"]["players"])
        assert rec["target_team_id"] == 2
        assert rec["trade_partner"] == "Partner Team"
