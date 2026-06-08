"""Tests for Sleeper / GSIS player id resolution."""

from unittest.mock import MagicMock

from app.services.fantasy_player_lookup import resolve_internal_player_id


def test_resolve_internal_player_id_by_platform_player_id():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (42,)

    assert resolve_internal_player_id(db, "9221") == 42
    db.execute.assert_called_once()


def test_resolve_internal_player_id_prefers_platform_over_numeric_internal():
    db = MagicMock()

    def execute_side_effect(stmt, params=None):
        query = MagicMock()
        if params and params.get("sleeper_id") == "4034":
            query.fetchone.return_value = (99,)
        else:
            query.fetchone.return_value = None
        return query

    db.execute.side_effect = execute_side_effect
    db.query.return_value.filter.return_value.first.return_value = None

    assert resolve_internal_player_id(db, "4034") == 99


def test_resolve_internal_player_id_gsis_bridge(monkeypatch):
    db = MagicMock()
    db.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=None)),
        MagicMock(fetchall=MagicMock(return_value=[(77, "1234"), (88, "5678")])),
    ]
    db.query.return_value.filter.return_value.first.return_value = None

    monkeypatch.setattr(
        "app.services.fantasy_player_lookup._sleeper_to_gsis_map",
        lambda: {"1234": "00-0039999", "5678": "00-0040000"},
    )

    assert resolve_internal_player_id(db, "5678") == 88
