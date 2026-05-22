"""
Tests for MLBStrikeoutSource.

Each test:
  1. Returns properly shaped candidates given fake DB rows.
  2. Returns [] when DB has no matching rows.
  3. Returns [] when DB query raises.
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

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

@pytest.mark.asyncio
async def test_mlb_strikeout_source_returns_candidates():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_fake_row()]

    source = MLBStrikeoutSource(db)
    results = await source.get_todays_projections(_date_range())

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


@pytest.mark.asyncio
async def test_mlb_strikeout_source_under_side():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_row(fanduel_over_under="UNDER")
    ]

    source = MLBStrikeoutSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results[0]["side"] == "under"


@pytest.mark.asyncio
async def test_mlb_strikeout_source_skips_no_line():
    """Rows without fanduel_line are omitted."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_row(fanduel_line=None)
    ]

    source = MLBStrikeoutSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []


# ---------------------------------------------------------------------------
# 2. Returns [] when no rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mlb_strikeout_source_empty_when_no_rows():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    source = MLBStrikeoutSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []


# ---------------------------------------------------------------------------
# 3. Returns [] on DB error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mlb_strikeout_source_returns_empty_on_db_error():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = RuntimeError("db down")

    source = MLBStrikeoutSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []
