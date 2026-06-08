"""Tests for Sleeper-first fantasy trade recommendations."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.fantasy_draft_picks import build_league_pick_registry
from app.services.fantasy_trade_recommendations import (
    build_faab_trade_recommendation,
    build_pick_trade_recommendation,
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


def _dynasty_league(**overrides):
    league = {
        "season": "2025",
        "total_rosters": 2,
        "settings": {"type": 2, "draft_rounds": 3, "waiver_budget": 0},
    }
    league.update(overrides)
    return league


def _tradeable_pick(season: int, round_num: int, owner: int = 1) -> dict:
    return {
        "season": season,
        "round": round_num,
        "roster_id": owner,
        "owner_id": owner,
        "previous_owner_id": owner,
    }


def test_build_pick_trade_recommendation_with_mock_registry():
    league = _dynasty_league()
    traded = [
        _tradeable_pick(2026, 1, 1),
        _tradeable_pick(2026, 2, 1),
        _tradeable_pick(2027, 1, 1),
    ]
    registry = build_league_pick_registry(league, traded)
    tradeable = [
        registry[pid] for pid in registry if int(registry[pid]["roster_id"]) == 1
    ]

    user_roster = [
        _player("RB One", "RB", 18.0),
        _player("RB Two", "RB", 16.0),
        _player("RB Three", "RB", 14.0),
        _player("RB Four", "RB", 12.0),
        _player("RB Five", "RB", 10.0),
        _player("WR One", "WR", 20.0),
        _player("WR Two", "WR", 18.0),
        _player("WR Three", "WR", 16.0),
        _player("TE One", "TE", 12.0),
    ]
    partner_roster = [
        _player("Partner QB", "QB", 35.0),
        _player("Partner QB2", "QB", 28.0),
        _player("Partner QB3", "QB", 22.0),
        _player("Partner RB", "RB", 20.0),
    ]

    rec = build_pick_trade_recommendation(
        need_position="QB",
        user_roster=user_roster,
        user_surplus=identify_position_surplus(count_positions(user_roster)),
        tradeable_picks=tradeable,
        partner_roster=partner_roster,
        partner_id=2,
        partner_name="Partner Team",
        pick_registry=registry,
        is_dynasty=True,
    )

    assert rec is not None
    assert rec["we_give"]["picks"]
    assert rec["we_give"]["players"]
    assert rec["we_get"]["players"]
    assert rec["we_give"]["faab"] == 0
    assert rec["we_get"]["faab"] == 0
    assert "Round" in rec["reasoning"] or "pick" in rec["reasoning"].lower()


def test_build_faab_trade_recommendation_when_budget_present():
    user_roster = [
        _player("RB One", "RB", 18.0),
        _player("RB Two", "RB", 16.0),
        _player("RB Three", "RB", 14.0),
        _player("RB Four", "RB", 12.0),
        _player("RB Five", "RB", 10.0),
        _player("WR One", "WR", 20.0),
        _player("WR Two", "WR", 18.0),
        _player("WR Three", "WR", 16.0),
        _player("TE One", "TE", 12.0),
    ]
    partner_roster = [
        _player("Partner QB", "QB", 35.0),
        _player("Partner QB2", "QB", 28.0),
        _player("Partner RB", "RB", 20.0),
    ]

    rec = build_faab_trade_recommendation(
        need_position="QB",
        user_roster=user_roster,
        user_surplus=identify_position_surplus(count_positions(user_roster)),
        faab_remaining=80,
        partner_roster=partner_roster,
        partner_id=2,
        partner_name="Partner Team",
    )

    assert rec is not None
    assert rec["we_give"]["faab"] > 0
    assert rec["we_give"]["faab"] <= 25
    assert rec["we_give"]["players"]
    assert rec["we_get"]["players"]


@pytest.mark.asyncio
@patch("app.services.fantasy_trade_recommendations.fetch_league_rosters")
@patch("app.services.fantasy_trade_recommendations.load_league_pick_context")
@patch("app.services.fantasy_trade_recommendations.fetch_team_roster_players")
async def test_generate_includes_dynasty_pick_recommendation(
    mock_fetch_roster,
    mock_pick_context,
    mock_fetch_league_rosters,
):
    user_roster = [
        _player("RB One", "RB", 18.0),
        _player("RB Two", "RB", 16.0),
        _player("RB Three", "RB", 14.0),
        _player("RB Four", "RB", 12.0),
        _player("RB Five", "RB", 10.0),
        _player("WR One", "WR", 20.0),
        _player("WR Two", "WR", 18.0),
        _player("WR Three", "WR", 16.0),
        _player("TE One", "TE", 12.0),
    ]
    partner_roster = [
        _player("Partner QB", "QB", 35.0),
        _player("Partner QB2", "QB", 28.0),
        _player("Partner QB3", "QB", 22.0),
        _player("Partner RB", "RB", 20.0),
    ]

    league = _dynasty_league()
    traded = [
        _tradeable_pick(2026, 1, 1),
        _tradeable_pick(2026, 2, 1),
        _tradeable_pick(2027, 1, 1),
    ]
    mock_pick_context.return_value = {
        "league": league,
        "traded_picks": traded,
        "pick_registry": build_league_pick_registry(league, traded),
        "is_dynasty": True,
        "league_format": {},
    }
    mock_fetch_league_rosters.return_value = [
        {"roster_id": 1, "settings": {"waiver_budget_used": 0}},
        {"roster_id": 2, "settings": {"waiver_budget_used": 0}},
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
        max_recommendations=15,
    )

    pick_recs = [rec for rec in recommendations if rec["type"] == "pick_trade"]
    assert pick_recs
    assert any(rec["we_give"]["picks"] for rec in pick_recs)


@pytest.mark.asyncio
@patch("app.services.fantasy_trade_recommendations.fetch_league_rosters")
@patch("app.services.fantasy_trade_recommendations.load_league_pick_context")
@patch("app.services.fantasy_trade_recommendations.fetch_team_roster_players")
async def test_generate_includes_faab_recommendation_when_waiver_budget_present(
    mock_fetch_roster,
    mock_pick_context,
    mock_fetch_league_rosters,
):
    user_roster = [
        _player("RB One", "RB", 18.0),
        _player("RB Two", "RB", 16.0),
        _player("RB Three", "RB", 14.0),
        _player("RB Four", "RB", 12.0),
        _player("RB Five", "RB", 10.0),
        _player("WR One", "WR", 20.0),
        _player("WR Two", "WR", 18.0),
        _player("WR Three", "WR", 16.0),
        _player("TE One", "TE", 12.0),
    ]
    partner_roster = [
        _player("Partner QB", "QB", 35.0),
        _player("Partner QB2", "QB", 28.0),
        _player("Partner RB", "RB", 20.0),
    ]

    league = _dynasty_league(
        settings={"type": 0, "draft_rounds": 2, "waiver_budget": 100}
    )
    mock_pick_context.return_value = {
        "league": league,
        "traded_picks": [],
        "pick_registry": build_league_pick_registry(league, []),
        "is_dynasty": False,
        "league_format": {},
    }
    mock_fetch_league_rosters.return_value = [
        {"roster_id": 1, "settings": {"waiver_budget_used": 10}},
        {"roster_id": 2, "settings": {"waiver_budget_used": 40}},
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
        max_recommendations=15,
    )

    faab_recs = [rec for rec in recommendations if rec["type"] == "faab_trade"]
    assert faab_recs
    assert faab_recs[0]["we_give"]["faab"] > 0


@pytest.mark.asyncio
@patch("app.services.fantasy_trade_recommendations.fetch_league_rosters")
@patch("app.services.fantasy_trade_recommendations.load_league_pick_context")
@patch("app.services.fantasy_trade_recommendations.fetch_team_roster_players")
async def test_generate_sleeper_trade_recommendations_never_empty_we_get(
    mock_fetch_roster,
    mock_pick_context,
    mock_fetch_league_rosters,
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

    league = _dynasty_league()
    mock_pick_context.return_value = {
        "league": league,
        "traded_picks": [],
        "pick_registry": build_league_pick_registry(league, []),
        "is_dynasty": True,
        "league_format": {},
    }
    mock_fetch_league_rosters.return_value = [
        {"roster_id": 1, "settings": {"waiver_budget_used": 0}},
        {"roster_id": 2, "settings": {"waiver_budget_used": 0}},
    ]
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
        assert "faab" in rec["we_give"]
        assert "faab" in rec["we_get"]
