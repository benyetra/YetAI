"""WNBA prop API ranking by season minutes per game."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.v1 import predictions as predictions_module


def _projection_row(row_id: int, player_id: int, name: str) -> SimpleNamespace:
    row = SimpleNamespace(
        id=row_id,
        date=date(2026, 6, 9),
        player_id=player_id,
        player_name=name,
        opponent_team_name="Opp",
        projected_points=10.0,
        market_line=None,
        edge=None,
        recommendation="NO_PLAY",
        confidence_score=None,
        created_at=None,
    )
    row.__table__ = SimpleNamespace(
        columns=[SimpleNamespace(name=n) for n in row.__dict__ if not n.startswith("_")]
    )
    return row


def test_wnba_props_ranked_by_season_mpg_not_row_id(monkeypatch):
    """High-minute marquee players beat recently-inserted low-minute rows."""
    db = MagicMock()
    model = MagicMock()
    model.date = MagicMock()

    projections = [
        _projection_row(4517, 1, "Bench Low Mins"),
        _projection_row(4458, 2, "Angel Reese"),
    ]
    db.query.return_value.filter.return_value.all.return_value = projections

    monkeypatch.setattr(
        predictions_module,
        "_load_wnba_season_minutes_avg",
        lambda _db, _ids, _as_of: {1: 8.0, 2: 28.5},
    )

    result = predictions_module._query_wnba_props_by_season_minutes(
        db,
        model,
        date(2026, 6, 9),
        75,
    )

    assert len(result) == 2
    assert result[0]["player_name"] == "Angel Reese"
    assert result[1]["player_name"] == "Bench Low Mins"


def test_wnba_props_caps_at_prop_limit(monkeypatch):
    db = MagicMock()
    model = MagicMock()
    model.date = MagicMock()

    projections = [_projection_row(100 + i, i, f"P{i}") for i in range(80)]
    db.query.return_value.filter.return_value.all.return_value = projections

    monkeypatch.setattr(
        predictions_module,
        "_load_wnba_season_minutes_avg",
        lambda _db, _ids, _as_of: {i: float(80 - i) for i in range(80)},
    )

    result = predictions_module._query_wnba_props_by_season_minutes(
        db,
        model,
        date(2026, 6, 9),
        75,
    )

    assert len(result) == 75
    assert result[0]["player_id"] == 0
    assert result[-1]["player_id"] == 74


def test_wnba_prop_default_limit_constant():
    assert predictions_module.WNBA_PROP_DEFAULT_LIMIT == 75
