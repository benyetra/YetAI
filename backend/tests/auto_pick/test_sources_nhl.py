"""
Tests for NHLGoalieSavesSource and NHLTotalsSource.
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources.nhl_goalie_saves_source import NHLGoalieSavesSource
from app.services.auto_pick.sources.nhl_totals_source import NHLTotalsSource


def _date_range():
    today = date.today()
    return DateRange(
        start=datetime.combine(today, datetime.min.time()),
        end=datetime.combine(today + timedelta(days=1), datetime.min.time()),
    )


# ---------------------------------------------------------------------------
# NHLGoalieSavesSource helpers
# ---------------------------------------------------------------------------

def _fake_goalie_row(
    goalie_id=42,
    goalie_name="Andrei Vasilevskiy",
    game_date=None,
    predicted_saves=28.5,
    saves_line=26.5,
    over_odds=-115,
    under_odds=-105,
    betting_recommendation="OVER 26.5",
    confidence=72.0,
    was_scratch=False,
):
    r = MagicMock()
    r.goalie_id = goalie_id
    r.goalie_name = goalie_name
    r.game_date = game_date or date.today()
    r.predicted_saves = predicted_saves
    r.saves_line = saves_line
    r.over_odds = over_odds
    r.under_odds = under_odds
    r.betting_recommendation = betting_recommendation
    r.confidence = confidence
    r.was_scratch = was_scratch
    return r


# ---------------------------------------------------------------------------
# 1. Returns properly shaped candidates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nhl_goalie_saves_source_returns_candidates():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_fake_goalie_row()]

    source = NHLGoalieSavesSource(db)
    results = await source.get_todays_projections(_date_range())

    assert len(results) == 1
    r = results[0]
    assert r["league"] == "NHL"
    assert r["stat"] == "saves"
    assert r["player"] == "Andrei Vasilevskiy"
    assert r["line"] == 26.5
    assert r["projection"] == 28.5
    assert r["side"] == "over"
    assert r["odds"] == -115
    assert "nhl-prop" in r["event_id"]
    assert "saves" in r["event_id"]
    assert abs(r["model_confidence"] - 0.72) < 0.001


@pytest.mark.asyncio
async def test_nhl_goalie_saves_source_under_side():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_goalie_row(betting_recommendation="UNDER 26.5")
    ]

    source = NHLGoalieSavesSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results[0]["side"] == "under"
    assert results[0]["odds"] == -105


@pytest.mark.asyncio
async def test_nhl_goalie_saves_source_skips_no_line():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_goalie_row(saves_line=None)
    ]

    source = NHLGoalieSavesSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []


# ---------------------------------------------------------------------------
# 2. Returns [] when no rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nhl_goalie_saves_source_empty_when_no_rows():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    source = NHLGoalieSavesSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []


# ---------------------------------------------------------------------------
# 3. Returns [] on DB error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nhl_goalie_saves_source_returns_empty_on_db_error():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = RuntimeError("db down")

    source = NHLGoalieSavesSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []


# ===========================================================================
# NHLTotalsSource
# ===========================================================================

def _fake_totals_row(
    game_date=None,
    home_team_name="Lightning",
    away_team_name="Rangers",
    predicted_total_goals=5.8,
    draftkings_ou_line=5.5,
    over_odds=-118,
    under_odds=-102,
    betting_recommendation="OVER",
    confidence=68.0,
    edge=0.3,
    prediction_date=None,
):
    r = MagicMock()
    r.game_date = game_date or date.today()
    r.home_team_name = home_team_name
    r.away_team_name = away_team_name
    r.predicted_total_goals = predicted_total_goals
    r.draftkings_ou_line = draftkings_ou_line
    r.over_odds = over_odds
    r.under_odds = under_odds
    r.betting_recommendation = betting_recommendation
    r.confidence = confidence
    r.edge = edge
    r.prediction_date = prediction_date or datetime.utcnow()
    return r


# ---------------------------------------------------------------------------
# 1. Returns properly shaped candidates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nhl_totals_source_returns_candidates():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [_fake_totals_row()]

    source = NHLTotalsSource(db)
    results = await source.get_todays_projections(_date_range())

    assert len(results) == 1
    r = results[0]
    assert r["league"] == "NHL"
    assert r["home_team_name"] == "Lightning"
    assert r["away_team_name"] == "Rangers"
    assert r["projected_total"] == 5.8
    assert r["market_total"] == 5.5
    assert r["side"] == "over"
    assert r["line_odds"] == -118
    assert "nhl-" in r["event_id"]
    assert abs(r["confidence_score"] - 0.68) < 0.001


@pytest.mark.asyncio
async def test_nhl_totals_source_under_side():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_totals_row(betting_recommendation="UNDER")
    ]

    source = NHLTotalsSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results[0]["side"] == "under"
    assert results[0]["line_odds"] == -102


@pytest.mark.asyncio
async def test_nhl_totals_source_skips_no_dk_line():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _fake_totals_row(draftkings_ou_line=None)
    ]

    source = NHLTotalsSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []


# ---------------------------------------------------------------------------
# 2. Returns [] when no rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nhl_totals_source_empty_when_no_rows():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    source = NHLTotalsSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []


# ---------------------------------------------------------------------------
# 3. Returns [] on DB error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nhl_totals_source_returns_empty_on_db_error():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = RuntimeError("db down")

    source = NHLTotalsSource(db)
    results = await source.get_todays_projections(_date_range())

    assert results == []
