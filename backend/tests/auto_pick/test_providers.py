import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from app.services.auto_pick.candidate import DateRange, MarketType
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.providers.totals_provider import TotalsCandidateProvider
from app.services.auto_pick.providers.moneyline_provider import (
    MoneylineCandidateProvider,
)


def _date_range():
    now = datetime.utcnow()
    return DateRange(now, now + timedelta(days=1))


# ---------------------------------------------------------------------------
# PlayerPropCandidateProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_player_prop_provider_returns_candidates():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(
        return_value=[
            {
                "league": "MLB",
                "event_id": "mlb-e1",
                "player": "Strider",
                "stat": "Ks",
                "line": 5.5,
                "side": "over",
                "odds": -115,
                "projection": 9.0,
                "sample_size": 7,
                "generated_at": "2026-05-22T08:00:00",
                "model_confidence": 0.78,
            },
        ]
    )
    p = PlayerPropCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert len(result) == 1
    assert result[0].market_type == MarketType.PLAYER_PROP
    assert result[0].our_projection == 9.0
    assert result[0].market_line == 5.5
    assert "Strider" in result[0].selection


@pytest.mark.asyncio
async def test_player_prop_provider_returns_empty_when_no_projections():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(return_value=[])
    p = PlayerPropCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert result == []


@pytest.mark.asyncio
async def test_player_prop_provider_swallows_source_errors():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(
        side_effect=RuntimeError("upstream down")
    )
    p = PlayerPropCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert result == []


# ---------------------------------------------------------------------------
# SpreadCandidateProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spread_provider_returns_candidates():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(
        return_value=[
            {
                "league": "NBA",
                "event_id": "nba-g1",
                "home_team_name": "Celtics",
                "away_team_name": "Lakers",
                "projected_margin": 6.2,
                "market_spread_home": -5.5,
                "spread_odds": -110,
                "side": "home",
                "edge": 0.7,
                "recommendation": "HOME",
                "confidence_score": 0.65,
                "home_win_prob": 0.72,
                "factors": {"method": "elo_pace"},
                "generated_at": "2026-05-22T09:00:00",
            },
        ]
    )
    p = SpreadCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert len(result) == 1
    assert result[0].market_type == MarketType.SPREAD
    assert result[0].our_projection == 6.2
    assert result[0].market_line == -5.5
    assert "Celtics" in result[0].selection


@pytest.mark.asyncio
async def test_spread_provider_returns_empty_when_no_projections():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(return_value=[])
    p = SpreadCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert result == []


@pytest.mark.asyncio
async def test_spread_provider_swallows_source_errors():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(
        side_effect=ConnectionError("db down")
    )
    p = SpreadCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert result == []


# ---------------------------------------------------------------------------
# TotalsCandidateProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_totals_provider_returns_candidates():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(
        return_value=[
            {
                "league": "NBA",
                "event_id": "nba-g2",
                "home_team_name": "Warriors",
                "away_team_name": "Suns",
                "projected_total": 228.4,
                "market_total": 224.5,
                "side": "over",
                "line_odds": -110,
                "edge": 3.9,
                "recommendation": "OVER",
                "confidence_score": 0.71,
                "factors": {},
                "injury_report": None,
                "generated_at": "2026-05-22T09:00:00",
            },
        ]
    )
    p = TotalsCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert len(result) == 1
    assert result[0].market_type == MarketType.TOTAL
    assert result[0].our_projection == 228.4
    assert result[0].market_line == 224.5
    assert "OVER" in result[0].selection


@pytest.mark.asyncio
async def test_totals_provider_returns_empty_when_no_projections():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(return_value=[])
    p = TotalsCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert result == []


@pytest.mark.asyncio
async def test_totals_provider_swallows_source_errors():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(side_effect=ValueError("bad data"))
    p = TotalsCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert result == []


# ---------------------------------------------------------------------------
# MoneylineCandidateProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_moneyline_provider_returns_candidates():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(
        return_value=[
            {
                "league": "NBA",
                "event_id": "nba-g3",
                "home_team_name": "Nuggets",
                "away_team_name": "Heat",
                "home_win_prob": 0.68,
                "moneyline_home": -210,
                "moneyline_away": 175,
                "side": "home",
                "confidence_score": 0.68,
                "generated_at": "2026-05-22T09:00:00",
            },
        ]
    )
    p = MoneylineCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert len(result) == 1
    assert result[0].market_type == MarketType.MONEYLINE
    assert result[0].our_projection == 0.68
    assert result[0].market_line == 0.0
    assert result[0].market_odds == -210
    assert "Nuggets" in result[0].selection
    assert "ML" in result[0].selection


@pytest.mark.asyncio
async def test_moneyline_provider_returns_empty_when_no_projections():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(return_value=[])
    p = MoneylineCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert result == []


@pytest.mark.asyncio
async def test_moneyline_provider_swallows_source_errors():
    fake_source = AsyncMock()
    fake_source.get_todays_projections = AsyncMock(
        side_effect=TimeoutError("service timeout")
    )
    p = MoneylineCandidateProvider(source=fake_source)
    result = await p.get_candidates(_date_range())
    assert result == []
