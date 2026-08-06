"""Unit tests for vault player label helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.league_vault.publish.players import (
    apply_player_labels_to_picks,
    resolve_player_labels,
    _label_from_sleeper,
)


def test_resolve_player_labels_empty_ids():
    assert resolve_player_labels(MagicMock(), set()) == {}


def test_resolve_player_labels_soft_fails():
    db = MagicMock()
    db.query.side_effect = RuntimeError("db down")
    assert resolve_player_labels(db, {"1"}) == {}


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
