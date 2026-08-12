"""API + config tests for NFL anytime-TD predictions."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.v1 import predictions as predictions_module
from app.services.etl.nfl.anytime_td_config import anytime_td_ui_enabled


def test_anytime_td_ui_enabled_default_off(monkeypatch):
    monkeypatch.delenv("NFL_ANYTIME_TD_UI", raising=False)
    assert anytime_td_ui_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_anytime_td_ui_enabled_truthy(monkeypatch, value):
    monkeypatch.setenv("NFL_ANYTIME_TD_UI", value)
    assert anytime_td_ui_enabled() is True


def test_anytime_td_positions():
    assert predictions_module.ANYTIME_TD_POSITIONS == frozenset(
        {"QB", "RB", "WR", "TE"}
    )


def _make_td_row(*, player_id: str, td_probability: float, row_id: int = 1):
    return SimpleNamespace(
        id=row_id,
        season=2026,
        week=1,
        player_id=player_id,
        td_probability=td_probability,
    )


def test_query_nfl_anytime_td_sorted_and_deduped(monkeypatch):
    rows = [
        _make_td_row(player_id="p1", td_probability=0.35, row_id=1),
        _make_td_row(player_id="p1", td_probability=0.55, row_id=2),
        _make_td_row(player_id="p2", td_probability=0.40, row_id=3),
    ]

    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.limit.return_value = mock_q
    mock_q.all.return_value = sorted(rows, key=lambda r: r.td_probability, reverse=True)

    mock_db = MagicMock()
    mock_db.query.return_value = mock_q

    monkeypatch.setattr(
        predictions_module,
        "_row_to_dict",
        lambda row: {
            "player_id": row.player_id,
            "td_probability": row.td_probability,
        },
    )

    out = predictions_module._query_nfl_anytime_td_predictions(
        mock_db, target_date=date(2026, 9, 7), limit=50
    )
    assert [r["player_id"] for r in out] == ["p1", "p2"]
    assert out[0]["td_probability"] == 0.55
    assert out[1]["td_probability"] == 0.40


def test_nfl_predictions_includes_anytime_td_key(monkeypatch):
    def fake_query_recent_nfl_with_fallback(
        db,
        model,
        date_col_name,
        target_date,
        limit,
        *,
        tz="UTC",
        dedupe_keys=None,
        latest_dedupe_keys=None,
    ):
        return []

    def fake_anytime_td(db, target_date, limit):
        return [{"player_id": "p1", "td_probability": 0.42}]

    monkeypatch.setattr(
        predictions_module,
        "_query_recent_nfl_with_fallback",
        fake_query_recent_nfl_with_fallback,
    )
    monkeypatch.setattr(
        predictions_module,
        "_query_nfl_anytime_td_predictions",
        fake_anytime_td,
    )
    monkeypatch.setattr(predictions_module, "enrich_prop_rows", lambda rows, **kw: rows)
    monkeypatch.setattr(
        predictions_module, "attach_team_opponent_fields", lambda rows: rows
    )
    monkeypatch.setattr(
        "app.services.game_projection_schedule.attach_game_times_from_lines",
        lambda db, rows, _m: rows,
    )

    result = predictions_module.nfl_predictions(
        target_date=date(2026, 9, 7),
        tz="UTC",
        limit=50,
        _user={"subscription_tier": "pro"},
        db=None,
    )

    assert "anytime_td_predictions" in result
    assert result["anytime_td_predictions"] == [
        {"player_id": "p1", "td_probability": 0.42}
    ]
