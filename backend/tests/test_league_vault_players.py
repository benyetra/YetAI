"""Unit tests for vault player label helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.league_vault.publish.players import (
    apply_player_labels_to_picks,
    normalize_draft_player_id,
    resolve_player_labels,
    _label_from_sleeper,
    _sleeper_catalog_index,
)


def test_resolve_player_labels_empty_ids():
    assert resolve_player_labels(MagicMock(), set()) == {}


def test_resolve_player_labels_soft_fails():
    db = MagicMock()
    db.query.side_effect = RuntimeError("db down")
    assert resolve_player_labels(db, {"1"}, allow_http=False) == {}


def test_normalize_draft_player_id_strips_espn_placeholders():
    assert normalize_draft_player_id("-1") is None
    assert normalize_draft_player_id(-1) is None
    assert normalize_draft_player_id("0") is None
    assert normalize_draft_player_id("4866") == "4866"
    assert normalize_draft_player_id(None) is None


def test_label_from_sleeper_prefers_full_name():
    row = SimpleNamespace(
        full_name="Saquon Barkley",
        first_name="Saquon",
        last_name="Barkley",
        position="RB",
        team="PHI",
    )
    assert _label_from_sleeper(row) == {
        "name": "Saquon Barkley",
        "position": "RB",
        "nfl_team": "PHI",
    }


def test_apply_player_labels_to_picks():
    picks = [{"player_id": "4866"}, {"player_id": None}]
    apply_player_labels_to_picks(
        picks,
        {"4866": {"name": "Saquon Barkley", "position": "RB", "nfl_team": "PHI"}},
    )
    assert picks[0]["player_name"] == "Saquon Barkley"
    assert picks[0]["player_position"] == "RB"
    assert picks[1]["player_name"] is None


def test_sleeper_catalog_indexes_espn_ids():
    raw = {
        "4866": {
            "full_name": "Saquon Barkley",
            "position": "RB",
            "team": "PHI",
            "espn_id": "3929630",
        }
    }
    with patch(
        "app.services.league_vault.publish.players._load_sleeper_players_raw",
        return_value=raw,
    ):
        index = _sleeper_catalog_index()
    assert index["4866"]["name"] == "Saquon Barkley"
    assert index["3929630"]["name"] == "Saquon Barkley"


def test_resolve_uses_sleeper_catalog_when_db_empty():
    db = MagicMock()
    db.query.side_effect = RuntimeError("no table")
    catalog = {
        "3929630": {"name": "Ja'Marr Chase", "position": "WR", "nfl_team": "CIN"}
    }
    with (
        patch(
            "app.services.league_vault.publish.players._sleeper_catalog_index",
            return_value=catalog,
        ),
        patch(
            "app.services.league_vault.publish.players._espn_athlete_labels",
            return_value={},
        ),
    ):
        out = resolve_player_labels(db, {"3929630"}, allow_http=True)
    assert out["3929630"]["name"] == "Ja'Marr Chase"
