"""Tests for Sleeper roster helpers used by trade analyzer."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.fantasy_sleeper_roster import (
    find_roster_for_team,
    fetch_team_players_by_position,
    format_sleeper_player_row,
)


def test_find_roster_for_team_matches_roster_id():
    rosters = [{"roster_id": 3, "players": ["p1"]}, {"roster_id": 7, "players": []}]
    assert find_roster_for_team(rosters, 3)["roster_id"] == 3
    assert find_roster_for_team(rosters, 99) is None


def test_format_sleeper_player_row_includes_trade_value():
    row = format_sleeper_player_row(
        "1234",
        {
            "first_name": "Test",
            "last_name": "Player",
            "position": "WR",
            "team": "KC",
            "age": 25,
        },
    )
    assert row["player_id"] == "1234"
    assert row["name"] == "Test Player"
    assert row["trade_value"] > 0


@pytest.mark.asyncio
async def test_fetch_team_players_by_position_returns_real_players_only(monkeypatch):
    sleeper = MagicMock()
    sleeper._get_all_players = AsyncMock(
        return_value={
            "qb1": {
                "first_name": "Real",
                "last_name": "QB",
                "position": "QB",
                "team": "BUF",
                "age": 28,
            },
            "wr1": {
                "first_name": "Real",
                "last_name": "WR",
                "position": "WR",
                "team": "KC",
                "age": 26,
            },
        }
    )

    async def fake_fetch_rosters(_league_id: str):
        return [{"roster_id": 2, "players": ["qb1", "wr1"]}]

    monkeypatch.setattr(
        "app.services.fantasy_sleeper_roster.fetch_league_rosters",
        fake_fetch_rosters,
    )

    players = await fetch_team_players_by_position(
        sleeper, "league-1", 2, "QB", limit=1
    )
    assert len(players) == 1
    assert players[0]["name"] == "Real QB"
    assert players[0]["id"] != "fallback_player"


@pytest.mark.asyncio
async def test_fetch_team_players_by_position_empty_when_missing(monkeypatch):
    sleeper = MagicMock()
    sleeper._get_all_players = AsyncMock(return_value={})

    async def fake_fetch_rosters(_league_id: str):
        return [{"roster_id": 2, "players": ["missing"]}]

    monkeypatch.setattr(
        "app.services.fantasy_sleeper_roster.fetch_league_rosters",
        fake_fetch_rosters,
    )
    players = await fetch_team_players_by_position(
        sleeper, "league-1", 2, "TE", limit=1
    )
    assert players == []
