"""Tests for player_analytics ETL (YetAI-ojg.4)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.services.etl.fantasy.sync_player_analytics import (
    _compute_ppr_points,
    sync_player_analytics,
)


def test_compute_ppr_points_from_box_score():
    row = pd.Series(
        {
            "passing_yards": 250,
            "passing_tds": 2,
            "interceptions": 1,
            "rushing_yards": 20,
            "rushing_tds": 0,
            "receptions": 0,
            "receiving_yards": 0,
            "receiving_tds": 0,
            "rushing_fumbles_lost": 0,
            "receiving_fumbles_lost": 0,
        }
    )
    points = _compute_ppr_points(row)
    # 250*0.04 + 2*4 - 1*2 + 20*0.1 = 10 + 8 - 2 + 2 = 18
    assert points == pytest.approx(18.0)


def test_compute_ppr_points_uses_nflverse_column_when_present():
    row = pd.Series({"fantasy_points_ppr": 21.7, "passing_yards": 0})
    assert _compute_ppr_points(row) == pytest.approx(21.7)


@pytest.mark.asyncio
async def test_sync_player_analytics_upserts_rows():
    db = MagicMock()
    existing_query = MagicMock()
    existing_query.filter.return_value.order_by.return_value.all.return_value = []
    db.query.return_value = existing_query

    weekly = pd.DataFrame(
        [
            {
                "player_id": "00-0031234",
                "week": 1,
                "season": 2024,
                "fantasy_points_ppr": 15.2,
                "targets": 8,
                "carries": 12,
                "receptions": 5,
                "receiving_yards": 60,
                "rushing_yards": 45,
                "opponent_team": "DAL",
                "target_share": 0.18,
                "offense_pct": 0.72,
            }
        ]
    )

    with (
        patch(
            "app.services.etl.fantasy.sync_player_analytics.fantasy_sleeper_unified.sync_fantasy_players",
            AsyncMock(return_value={"created": 1, "updated": 0, "total_processed": 1}),
        ),
        patch(
            "app.services.etl.fantasy.sync_player_analytics._build_gsis_to_fantasy_player_map",
            AsyncMock(return_value={"00-0031234": 42}),
        ),
        patch(
            "app.services.etl.fantasy.sync_player_analytics._load_weekly_frame",
            return_value=weekly,
        ),
    ):
        result = await sync_player_analytics(db, season=2024)

    assert result["rows_upserted"] == 1
    assert result["season"] == 2024
    db.bulk_insert_mappings.assert_called_once()
    db.commit.assert_called_once()
