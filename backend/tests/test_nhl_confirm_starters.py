"""Tests for NHL starter confirmation before goalie predictions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
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


@patch("app.services.etl.nhl.confirm_starters.db_goalie_by_player_id")
def test_resolve_predicts_announced_backup(mock_by_id):
    """No DB-primary gate: whoever is the listed starter is predicted."""
    mock_by_id.return_value = _primary_goalie(200, "Backup Two", "New York")

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

    assert ctx.should_predict is True
    assert ctx.goalie_id == 200
    assert (ctx.method, ctx.source) == ("confirmed", "nhl_boxscore")


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


@patch("app.services.etl.nhl.confirm_starters.fetch_espn_probables", return_value={})
@patch("app.services.etl.nhl.confirm_starters.db_goalie_by_player_id")
@patch("app.services.etl.nhl.confirm_starters.get_starters_from_boxscore")
def test_build_slate_skips_slot_without_starter(mock_starters, mock_by_id, _espn):
    mock_starters.return_value = (_api_starter(100, "Home Starter"), None)
    mock_by_id.return_value = _primary_goalie(100, "Home Starter", "New York")

    summary = cs.build_slate_starter_context([_game()], client=MagicMock())

    home_slot, away_slot = summary.slots
    assert home_slot.should_predict is True
    assert away_slot.should_predict is False
    assert away_slot.prediction_skipped_reason == cs.SKIP_STARTER_UNCONFIRMED
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
        prediction_skipped_reason=cs.SKIP_NO_DB_GOALIE,
    )
    meta = cs.starter_features_metadata(ctx)
    assert meta["prediction_skipped_reason"] == cs.SKIP_NO_DB_GOALIE
    assert meta["starter_confirmation"]["starter_confirmed"] is True


# --- ESPN probables + roster mapping (real 2026-11-13 payloads) -------------------

FIX = Path(__file__).parent / "fixtures" / "nhl"


def _fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_fetch_espn_probables_parses_real_scoreboard():
    resp = MagicMock()
    resp.json.return_value = _fixture("espn_nhl_scoreboard_20261113.json")
    with patch.object(cs.requests, "get", return_value=resp):
        out = cs.fetch_espn_probables(date(2026, 11, 13))
    assert out["new york rangers"] == ("Dylan Garand", "confirmed")
    assert out["vancouver canucks"] == ("Leevi Merilainen", "probable")


def test_fetch_espn_probables_error_returns_empty():
    with patch.object(cs.requests, "get", side_effect=RuntimeError("boom")):
        assert cs.fetch_espn_probables(date(2026, 11, 13)) == {}


def test_roster_match_handles_diacritics_and_last_name_fallback():
    goalies = _fixture("nhl_roster_VAN.json")["goalies"]
    assert cs.match_roster_goalie(goalies, "Leevi Merilainen")["id"] == 8482447
    assert cs.match_roster_goalie(goalies, "L. Merilainen")["id"] == 8482447
    assert cs.match_roster_goalie(goalies, "Nobody Else") is None


def test_resolve_prefers_boxscore_over_espn_and_marks_probable():
    espn = {"id": 5, "full_name": "Espn Guy", "method": "probable"}
    kw = dict(
        game_id=1,
        game_date=date(2026, 5, 23),
        game_time=None,
        is_home=True,
        team_id=10,
        team_name="New York",
        opponent_team_id=6,
        opponent_team_name="Boston",
    )
    with patch.object(
        cs, "db_goalie_by_player_id", side_effect=lambda i: _primary_goalie(i, "G", "x")
    ):
        both = cs.resolve_goalie_slot(
            **kw, api_starter=_api_starter(9, "Box Guy"), espn_starter=espn
        )
        only_espn = cs.resolve_goalie_slot(**kw, api_starter=None, espn_starter=espn)
    assert (both.goalie_id, both.method, both.source) == (
        9,
        "confirmed",
        "nhl_boxscore",
    )
    assert both.confidence == cs.CONFIDENCE_CONFIRMED_PRIMARY
    assert (only_espn.goalie_id, only_espn.method, only_espn.source) == (
        5,
        "probable",
        "espn",
    )
    assert only_espn.starter_confirmed is False
    assert only_espn.confidence == cs.CONFIDENCE_PROBABLE
    meta = cs.starter_features_metadata(only_espn)["starter_confirmation"]
    assert meta["method"] == "probable" and meta["full_name"] == "Espn Guy"


def test_resolve_skips_no_db_goalie():
    with patch.object(cs, "db_goalie_by_player_id", return_value=None):
        ctx = cs.resolve_goalie_slot(
            game_id=1,
            game_date=date(2026, 5, 23),
            game_time=None,
            is_home=True,
            team_id=10,
            team_name="New York",
            opponent_team_id=6,
            opponent_team_name="Boston",
            api_starter=_api_starter(9, "Box Guy"),
        )
    assert ctx.should_predict is False
    assert ctx.prediction_skipped_reason == cs.SKIP_NO_DB_GOALIE


def test_build_slate_maps_espn_probables_to_nhl_ids():
    game = {
        "id": 2026020310,
        "startTimeUTC": "2026-11-13T23:00:00Z",
        "homeTeam": {
            "id": 23,
            "abbrev": "VAN",
            "placeName": {"default": "Vancouver"},
        },
        "awayTeam": {
            "id": 3,
            "abbrev": "NYR",
            "placeName": {"default": "New York"},
        },
    }
    client = MagicMock()
    client.get_game_boxscore.return_value = {}
    client.get_team_roster.side_effect = lambda a: _fixture(f"nhl_roster_{a}.json")
    resp = MagicMock()
    resp.json.return_value = _fixture("espn_nhl_scoreboard_20261113.json")
    with (
        patch.object(cs.requests, "get", return_value=resp) as get,
        patch.object(
            cs,
            "db_goalie_by_player_id",
            side_effect=lambda i: _primary_goalie(i, "db", "x"),
        ),
    ):
        summary = cs.build_slate_starter_context([game, game], client=client)
    assert get.call_count == 1  # one ESPN fetch per ET game date
    home, away = summary.slots[:2]
    assert (home.goalie_id, home.method, home.full_name) == (
        8482447,
        "probable",
        "Leevi Merilainen",
    )
    assert (away.method, away.full_name) == ("confirmed", "Dylan Garand")
    assert client.get_team_roster.call_count == 2  # roster cached per abbrev


def _resp(status, payload=None, headers=None):
    return SimpleNamespace(
        status_code=status, json=lambda: payload, headers=headers or {}
    )


def test_client_retries_once_on_429_then_succeeds():
    from app.services.etl.nhl import nhl_api_client as nc

    with (
        patch.object(
            nc.requests,
            "get",
            side_effect=[
                _resp(429, headers={"Retry-After": "0"}),
                _resp(200, {"ok": 1}),
            ],
        ) as get,
        patch.object(nc.time, "sleep"),
    ):
        assert nc.NHLAPIClient().get_team_roster("VAN") == {"ok": 1}
    assert get.call_count == 2 and get.call_args.kwargs["timeout"] == 10


def test_client_backs_off_on_429_then_gives_up_without_crash():
    from app.services.etl.nhl import nhl_api_client as nc

    with (
        patch.object(nc.requests, "get", return_value=_resp(429)) as get,
        patch.object(nc.time, "sleep") as sleep,
    ):
        assert nc.NHLAPIClient().get_team_roster("VAN") is None
    assert get.call_count == 5  # first try + 4 backoffs
    assert [c.args[0] for c in sleep.call_args_list] == [2.0, 4.0, 8.0, 16.0]


def test_build_slate_warns_when_slot_dropped(caplog):
    game = _game()
    with (
        patch.object(cs, "fetch_espn_probables", return_value={}),
        patch.object(cs, "get_starters_from_boxscore", return_value=(None, None)),
        caplog.at_level("WARNING", logger=cs.logger.name),
    ):
        summary = cs.build_slate_starter_context([game], client=MagicMock())
    assert summary.skipped == 2
    assert "Goalie slot dropped" in caplog.text


def test_build_slate_skips_boxscore_for_far_future_game():
    game = {**_game(), "gameState": "FUT", "startTimeUTC": "2099-01-01T00:00:00Z"}
    with (
        patch.object(cs, "fetch_espn_probables", return_value={}),
        patch.object(cs, "get_starters_from_boxscore") as box,
    ):
        cs.build_slate_starter_context([game], client=MagicMock())
    box.assert_not_called()


def test_espn_spelling_kept_over_roster_spelling():
    espn = {"id": 7, "full_name": "Sam Montembeault", "method": "probable"}
    with patch.object(
        cs, "db_goalie_by_player_id", side_effect=lambda i: _primary_goalie(i, "G", "x")
    ):
        ctx = cs.resolve_goalie_slot(
            game_id=1,
            game_date=date(2026, 5, 23),
            game_time=None,
            is_home=True,
            team_id=10,
            team_name="Montreal",
            opponent_team_id=6,
            opponent_team_name="Boston",
            api_starter=None,
            espn_starter=espn,
            roster_name="Samuel Montembeault",
        )
    assert ctx.full_name == "Sam Montembeault"
