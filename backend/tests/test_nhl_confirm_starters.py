"""Tests for NHL starter confirmation before goalie predictions."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.nhl import confirm_starters as cs


def _api_starter(player_id: int, name: str) -> dict:
    return {"playerId": player_id, "starter": True, "name": {"default": name}}


def _boxscore(home_starter: dict | None, away_starter: dict | None) -> dict:
    return {
        "playerByGameStats": {
            "homeTeam": {"goalies": [home_starter] if home_starter else []},
            "awayTeam": {"goalies": [away_starter] if away_starter else []},
        }
    }


def _game(game_id: int = 2025020001) -> dict:
    return {
        "id": game_id,
        "startTimeUTC": "2026-05-23T23:00:00Z",
        "homeTeam": {
            "id": 10,
            "abbrev": "NYR",
            "placeName": {"default": "New York"},
        },
        "awayTeam": {
            "id": 6,
            "abbrev": "BOS",
            "placeName": {"default": "Boston"},
        },
    }


def _primary_goalie(player_id: int, name: str, team: str) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=player_id, name=name, team_name=team, games_played=40
    )


@patch("app.services.etl.nhl.confirm_starters.db_session")
def test_resolve_skips_when_backup_announced(mock_db):
    primary = _primary_goalie(100, "Starter One", "New York")
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
        primary
    )
    mock_db.query.return_value.filter.return_value.first.return_value = None

    ctx = cs.resolve_goalie_slot(
        game_id=1,
        game_date=date(2026, 5, 23),
        game_time=None,
        is_home=True,
        team_id=10,
        team_name="New York",
        opponent_team_id=6,
        opponent_team_name="Boston",
        api_starter=_api_starter(200, "Backup Two"),
    )

    assert ctx.should_predict is False
    assert ctx.prediction_skipped_reason == cs.SKIP_BACKUP_EXPECTED
    assert ctx.starter_confirmed is True
    assert ctx.goalie_id == 200


@patch("app.services.etl.nhl.confirm_starters.db_session")
def test_resolve_predicts_when_primary_confirmed(mock_db):
    primary = _primary_goalie(100, "Starter One", "New York")

    def query_side_effect(model):
        q = MagicMock()
        if hasattr(model, "__name__") and model.__name__ == "NHLGoalie":
            q.filter.return_value.order_by.return_value.first.return_value = primary
            q.filter.return_value.first.return_value = primary
        return q

    mock_db.query.side_effect = query_side_effect

    ctx = cs.resolve_goalie_slot(
        game_id=1,
        game_date=date(2026, 5, 23),
        game_time=None,
        is_home=True,
        team_id=10,
        team_name="New York",
        opponent_team_id=6,
        opponent_team_name="Boston",
        api_starter=_api_starter(100, "Starter One"),
    )

    assert ctx.should_predict is True
    assert ctx.starter_confirmed is True
    assert ctx.prediction_skipped_reason is None
    assert ctx.confidence == cs.CONFIDENCE_CONFIRMED_PRIMARY
    assert ctx.goalie_id == 100


@patch("app.services.etl.nhl.confirm_starters.db_session")
def test_resolve_skips_when_starter_unconfirmed(mock_db):
    primary = _primary_goalie(100, "Starter One", "New York")
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
        primary
    )

    ctx = cs.resolve_goalie_slot(
        game_id=1,
        game_date=date(2026, 5, 23),
        game_time=None,
        is_home=True,
        team_id=10,
        team_name="New York",
        opponent_team_id=6,
        opponent_team_name="Boston",
        api_starter=None,
    )

    assert ctx.should_predict is False
    assert ctx.prediction_skipped_reason == cs.SKIP_STARTER_UNCONFIRMED
    assert ctx.starter_confirmed is False


@patch("app.services.etl.nhl.confirm_starters.primary_db_goalie")
@patch("app.services.etl.nhl.confirm_starters.get_starters_from_boxscore")
def test_build_slate_skips_backup_slot(mock_starters, mock_primary):
    mock_starters.return_value = (
        _api_starter(100, "Home Starter"),
        _api_starter(300, "Away Backup"),
    )
    mock_primary.side_effect = [
        _primary_goalie(100, "Home Starter", "New York"),
        _primary_goalie(400, "Away Primary", "Boston"),
    ]

    client = MagicMock()
    summary = cs.build_slate_starter_context([_game()], client=client)

    assert len(summary.slots) == 2
    home_slot, away_slot = summary.slots
    assert home_slot.should_predict is True
    assert away_slot.should_predict is False
    assert away_slot.prediction_skipped_reason == cs.SKIP_BACKUP_EXPECTED
    assert summary.skipped == 1
    assert summary.predicted_eligible == 1


def test_get_starters_from_boxscore_parses_starter_flag():
    client = MagicMock()
    client.get_game_boxscore.return_value = _boxscore(
        _api_starter(1, "A"),
        _api_starter(2, "B"),
    )
    home, away = cs.get_starters_from_boxscore(client, 99)
    assert home["playerId"] == 1
    assert away["playerId"] == 2


def test_starter_features_metadata_includes_skip_reason():
    ctx = cs.GoalieStarterContext(
        game_id=1,
        game_date=date(2026, 5, 23),
        game_time=None,
        is_home=False,
        team_id=6,
        team_name="Boston",
        opponent_team_id=10,
        opponent_team_name="New York",
        goalie_id=300,
        goalie_name="Backup",
        starter_confirmed=True,
        confidence=95.0,
        should_predict=False,
        prediction_skipped_reason=cs.SKIP_BACKUP_EXPECTED,
    )
    meta = cs.starter_features_metadata(ctx)
    assert meta["prediction_skipped_reason"] == cs.SKIP_BACKUP_EXPECTED
    assert meta["starter_confirmation"]["starter_confirmed"] is True
