"""Tests for Sleeper/internal trade player resolution."""

from unittest.mock import MagicMock

from app.models.database_models import SleeperPlayer
from app.models.fantasy_models import FantasyPlatform, FantasyPlayer
from app.services.fantasy_trade_players import resolve_trade_player


def test_resolve_trade_player_by_sleeper_id_from_sleeper_table():
    db = MagicMock()
    sleeper_row = SleeperPlayer(
        sleeper_player_id="9999",
        full_name="Test Player",
        position="WR",
        team="KC",
        age=26,
        injury_status=None,
    )

    def query_side_effect(model):
        query = MagicMock()
        if model is FantasyPlayer:
            query.filter.return_value.first.return_value = None
        elif model is SleeperPlayer:
            query.filter.return_value.first.return_value = sleeper_row
        return query

    db.query.side_effect = query_side_effect

    resolved = resolve_trade_player(db, "9999")
    assert resolved is not None
    assert resolved.sleeper_id == "9999"
    assert resolved.internal_id is None
    assert resolved.name == "Test Player"
    assert resolved.position == "WR"


def test_resolve_trade_player_by_internal_id():
    db = MagicMock()
    fantasy_player = FantasyPlayer(
        id=42,
        platform=FantasyPlatform.SLEEPER,
        platform_player_id="8888",
        name="Internal Player",
        position="RB",
        team="DAL",
        age=24,
    )

    def query_side_effect(model):
        query = MagicMock()
        if model is FantasyPlayer:
            query.filter.return_value.first.return_value = fantasy_player
        return query

    db.query.side_effect = query_side_effect

    resolved = resolve_trade_player(db, 42)
    assert resolved is not None
    assert resolved.internal_id == 42
    assert resolved.sleeper_id == "8888"
