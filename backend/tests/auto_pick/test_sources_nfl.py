"""
Tests for NFLQBPassingSource.
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources.nfl_qb_passing_source import NFLQBPassingSource


def _date_range():
    today = date.today()
    return DateRange(
        start=datetime.combine(today, datetime.min.time()),
        end=datetime.combine(today + timedelta(days=1), datetime.min.time()),
    )


def _fake_qb_row(
    qb_player_id="qb1",
    qb_player_name="Patrick Mahomes",
    game_date=None,
    predicted_passing_yards=285.4,
    ou_line=271.5,
    over_odds=-115,
    under_odds=-105,
    betting_recommendation="OVER",
    model_confidence=0.74,
):
    r = MagicMock()
    r.qb_player_id = qb_player_id
    r.qb_player_name = qb_player_name
    # game_date is DateTime in the model
    r.game_date = datetime.combine(game_date or date.today(), datetime.min.time())
    r.predicted_passing_yards = predicted_passing_yards
    r.ou_line = ou_line
    r.over_odds = over_odds
    r.under_odds = under_odds
    r.betting_recommendation = betting_recommendation
    r.model_confidence = model_confidence
    return r


# ---------------------------------------------------------------------------
# 1. Returns properly shaped candidates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nfl_qb_passing_source_returns_candidates():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_fake_qb_row()]

    source = NFLQBPassingSource(db)
    results = await source.get_todays_projections(_date_range())

    assert len(results) == 1
    r = results[0]
    assert r["league"] == "NFL"
    assert r["stat"] == "passing_yards"
    assert r["player"] == "Patrick Mahomes"
    assert r["line"] == 271.5
    assert r["projection"] == 285.4
    assert r["side"] == "over"
    assert r["odds"] == -115
    assert r["model_confidence"] == 0.74
    assert "nfl-prop" in r["event_id"]
    assert "passing_yards" in r["event_id"]


@pytest.mark.asyncio
async def test_nfl_qb_passing_source_under_side():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_qb_row(betting_recommendation="UNDER")
    ]

    source = NFLQBPassingSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results[0]["side"] == "under"
    assert results[0]["odds"] == -105


@pytest.mark.asyncio
async def test_nfl_qb_passing_source_skips_no_ou_line():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_qb_row(ou_line=None)
    ]

    source = NFLQBPassingSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []


# ---------------------------------------------------------------------------
# 2. Returns [] when no rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nfl_qb_passing_source_empty_when_no_rows():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    source = NFLQBPassingSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []


# ---------------------------------------------------------------------------
# 3. Returns [] on DB error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nfl_qb_passing_source_returns_empty_on_db_error():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = RuntimeError("db down")

    source = NFLQBPassingSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []
