"""
Tests for MLBStrikeoutSource.

Each test:
  1. Returns properly shaped candidates given fake DB rows.
  2. Returns [] when DB has no matching rows.
  3. Returns [] when DB query raises.
"""

import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources.mlb_strikeout_source import MLBStrikeoutSource


def _date_range():
    today = date.today()
    return DateRange(
        start=datetime.combine(today, datetime.min.time()),
        end=datetime.combine(today + timedelta(days=1), datetime.min.time()),
    )


def _fake_row(
    pitcher_id="p1",
    pitcher_name="Spencer Strider",
    date_val=None,
    projected_strikeouts=9.2,
    fanduel_line=6.5,
    fanduel_over_under="OVER",
):
    r = MagicMock()
    r.pitcher_id = pitcher_id
    r.pitcher_name = pitcher_name
    r.date = date_val or date.today()
    r.projected_strikeouts = projected_strikeouts
    r.fanduel_line = fanduel_line
    r.fanduel_over_under = fanduel_over_under
    return r


# ---------------------------------------------------------------------------
# 1. Returns properly shaped candidates
# ---------------------------------------------------------------------------


def test_mlb_strikeout_source_returns_candidates():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_fake_row()]

    source = MLBStrikeoutSource(db)
    results = asyncio.run(source.get_todays_projections(_date_range()))

    assert len(results) == 1
    r = results[0]
    assert r["league"] == "MLB"
    assert r["stat"] == "strikeouts"
    assert r["player"] == "Spencer Strider"
    assert r["line"] == 6.5
    assert r["projection"] == 9.2
    assert r["side"] == "over"
    assert r["odds"] == -110
    assert "mlb-prop" in r["event_id"]
    assert "strikeouts" in r["event_id"]


def test_mlb_strikeout_source_under_side():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_row(fanduel_over_under="UNDER")
    ]

    source = MLBStrikeoutSource(db)
    results = asyncio.run(source.get_todays_projections(_date_range()))

    assert results[0]["side"] == "under"


def test_mlb_strikeout_source_skips_low_edge():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_row(projected_strikeouts=5.6, fanduel_line=5.5, fanduel_over_under="over")
    ]
    db.query.return_value.all.return_value = []

    source = MLBStrikeoutSource(db)
    results = asyncio.run(source.get_todays_projections(_date_range()))

    assert results == []


def test_mlb_strikeout_source_uses_projection_pick_when_ou_missing():
    db = MagicMock()
    strikeout_q = MagicMock()
    strikeout_q.filter.return_value.all.return_value = [
        _fake_row(projected_strikeouts=8.2, fanduel_line=5.5, fanduel_over_under=None)
    ]
    pitcher_q = MagicMock()
    pitcher_q.all.return_value = []

    def _query(model):
        if getattr(model, "__name__", "") == "StrikeoutProjections":
            return strikeout_q
        return pitcher_q

    db.query.side_effect = _query

    source = MLBStrikeoutSource(db)
    results = asyncio.run(source.get_todays_projections(_date_range()))

    assert len(results) == 1
    assert results[0]["side"] == "over"
    assert results[0]["model_confidence"] is not None


def test_mlb_strikeout_source_skips_no_line():
    """Rows without fanduel_line are omitted."""
    db = MagicMock()
    strikeout_q = MagicMock()
    strikeout_q.filter.return_value.all.return_value = [_fake_row(fanduel_line=None)]
    pitcher_q = MagicMock()
    pitcher_q.all.return_value = []

    def _query(model):
        if getattr(model, "__name__", "") == "StrikeoutProjections":
            return strikeout_q
        return pitcher_q

    db.query.side_effect = _query

    source = MLBStrikeoutSource(db)
    results = asyncio.run(source.get_todays_projections(_date_range()))

    assert results == []


# ---------------------------------------------------------------------------
# 2. Returns [] when no rows
# ---------------------------------------------------------------------------


def test_mlb_strikeout_source_empty_when_no_rows():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    source = MLBStrikeoutSource(db)
    results = asyncio.run(source.get_todays_projections(_date_range()))

    assert results == []


# ---------------------------------------------------------------------------
# 3. Returns [] on DB error
# ---------------------------------------------------------------------------


def test_mlb_strikeout_source_returns_empty_on_db_error():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = RuntimeError("db down")

    source = MLBStrikeoutSource(db)
    results = asyncio.run(source.get_todays_projections(_date_range()))

    assert results == []
