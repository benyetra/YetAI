"""Tests for fantasy player compare service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.fantasy_player_compare import (
    _aggregate_analytics,
    _derive_trends,
    generate_compare_insights,
    enrich_players_with_analytics,
)


def test_aggregate_analytics_computes_ppg_and_consistency():
    rows = [
        {"ppr_points": 20, "carries": 10, "targets": 5, "rushing_yards": 50},
        {"ppr_points": 10, "carries": 8, "targets": 3, "rushing_yards": 40},
    ]
    agg = _aggregate_analytics(rows)
    assert agg["points_per_touch"] == pytest.approx(30 / 26)
    assert 0 <= agg["consistency_score"] <= 1


def test_derive_trends_up_when_recent_higher():
    rows = [
        {"week": 6, "ppr_points": 25},
        {"week": 5, "ppr_points": 22},
        {"week": 4, "ppr_points": 20},
        {"week": 3, "ppr_points": 8},
        {"week": 2, "ppr_points": 9},
        {"week": 1, "ppr_points": 7},
    ]
    trends = _derive_trends(rows)
    assert trends["trend_direction"] == "up"
    assert trends["recent_avg"] > trends["previous_avg"]


def test_generate_compare_insights_picks_scoring_leader():
    players = [
        {
            "name": "Alpha",
            "injury_status": "Healthy",
            "analytics": {"points_per_game": 18.0, "snap_percentage": 70},
            "trends": {},
        },
        {
            "name": "Beta",
            "injury_status": "Healthy",
            "analytics": {"points_per_game": 12.0, "snap_percentage": 65},
            "trends": {},
        },
    ]
    insights = generate_compare_insights(players)
    assert any("Alpha" in i and "scoring" in i for i in insights)


def test_format_roster_traded_picks():
    from app.api.fantasy.trade_value import format_roster_traded_picks

    raw = [
        {
            "season": "2025",
            "round": 1,
            "roster_id": 2,
            "owner_id": 2,
            "previous_owner_id": 1,
        },
        {
            "season": "2026",
            "round": 2,
            "roster_id": 3,
            "owner_id": 3,
            "previous_owner_id": 3,
        },
    ]
    picks = format_roster_traded_picks(raw, roster_id=2)
    assert len(picks) == 1
    assert picks[0]["season"] == 2025
    assert picks[0]["round"] == 1
    assert picks[0]["trade_value"] > 0


@pytest.mark.asyncio
async def test_enrich_players_without_mapping_returns_empty_analytics():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = None
    players = [{"player_id": "9999", "name": "Unknown"}]
    result = await enrich_players_with_analytics(db, players, season=2025)
    assert result[0]["analytics"] == {}


@pytest.mark.asyncio
async def test_enrich_players_with_mapping_calls_analytics_service():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (42,)

    mock_service_instance = MagicMock()
    mock_service_instance.get_player_analytics = AsyncMock(
        return_value=[{"week": 1, "ppr_points": 15.0, "snap_percentage": 80}]
    )

    with pytest.MonkeyPatch.context() as mp:
        from app.services import fantasy_player_compare as mod

        mp.setattr(
            mod,
            "PlayerAnalyticsService",
            lambda _db: mock_service_instance,
        )
        result = await enrich_players_with_analytics(
            db, [{"player_id": "1234", "name": "Test"}], season=2025
        )

    assert result[0]["season_stats"]["games_played"] == 1
    assert result[0]["analytics"]["snap_percentage"] == 80
