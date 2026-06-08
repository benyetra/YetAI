"""Tests for player_analytics ETL (YetAI-ojg.4)."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.services.etl.fantasy.sync_player_analytics import (
    _compute_ppr_points,
    _normalize_snap_percentage,
    _row_payload,
    sync_player_analytics,
)
from app.services.player_analytics_service import PlayerAnalyticsService


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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (0.72, 72.0),
        (1.0, 100.0),
        (72.0, 72.0),
        (100.0, 100.0),
    ],
)
def test_normalize_snap_percentage(raw, expected):
    result = _normalize_snap_percentage(raw)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_row_payload_merges_snap_lookup_when_weekly_lacks_offense_pct():
    row = pd.Series(
        {
            "player_id": "00-0031234",
            "week": 1,
            "fantasy_points_ppr": 12.0,
            "targets": 4,
            "carries": 10,
            "receptions": 3,
            "receiving_yards": 30,
            "rushing_yards": 40,
            "opponent_team": "KC",
        }
    )
    payload = _row_payload(
        row=row,
        fantasy_player_id=42,
        week=1,
        season=2025,
        snap_lookup={("00-0031234", 1): 0.68},
    )
    assert payload["snap_percentage"] == pytest.approx(68.0)


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
        patch(
            "app.services.etl.fantasy.sync_player_analytics._build_gsis_week_snap_lookup",
            return_value={},
        ),
    ):
        result = await sync_player_analytics(db, season=2024)

    assert result["rows_upserted"] == 1
    assert result["season"] == 2024
    db.bulk_insert_mappings.assert_called_once()
    inserted = db.bulk_insert_mappings.call_args[0][1][0]
    assert inserted["snap_percentage"] == pytest.approx(72.0)
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_sync_player_analytics_merges_snap_counts_when_offense_pct_missing():
    db = MagicMock()
    existing_query = MagicMock()
    existing_query.filter.return_value.order_by.return_value.all.return_value = []
    db.query.return_value = existing_query

    weekly = pd.DataFrame(
        [
            {
                "player_id": "00-0031234",
                "week": 1,
                "season": 2025,
                "fantasy_points_ppr": 14.0,
                "targets": 6,
                "carries": 8,
                "receptions": 4,
                "receiving_yards": 50,
                "rushing_yards": 25,
                "opponent_team": "BUF",
                "target_share": 0.15,
            }
        ]
    )

    with (
        patch(
            "app.services.etl.fantasy.sync_player_analytics._build_gsis_to_fantasy_player_map",
            AsyncMock(return_value={"00-0031234": 42}),
        ),
        patch(
            "app.services.etl.fantasy.sync_player_analytics._load_weekly_frame",
            return_value=weekly,
        ),
        patch(
            "app.services.etl.fantasy.sync_player_analytics._build_gsis_week_snap_lookup",
            return_value={("00-0031234", 1): 0.81},
        ),
    ):
        result = await sync_player_analytics(db, season=2025)

    assert result["rows_upserted"] == 1
    inserted = db.bulk_insert_mappings.call_args[0][1][0]
    assert inserted["snap_percentage"] == pytest.approx(81.0)


@pytest.mark.asyncio
async def test_get_player_analytics_normalizes_fraction_snap_percentage():
    db = MagicMock()
    result_mock = MagicMock()
    result_mock.fetchall.return_value = [
        (
            1,
            2025,
            15.0,
            0.72,
            0.18,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "DAL",
            None,
            None,
            10,
            40,
            4,
            50,
            6,
            13.0,
            11.0,
        )
    ]
    db.execute.return_value = result_mock

    service = PlayerAnalyticsService(db)
    analytics = await service.get_player_analytics(42, season=2025)

    assert len(analytics) == 1
    assert analytics[0]["snap_percentage"] == pytest.approx(72.0)


def test_load_weekly_frame_falls_back_to_stats_player_release():
    from urllib.error import HTTPError

    from app.services.etl.fantasy.sync_player_analytics import _load_weekly_frame

    legacy_error = HTTPError(
        "https://example.com/player_stats_2025.parquet", 404, "Not Found", {}, None
    )
    fallback_df = pd.DataFrame(
        [
            {
                "player_id": "00-0031234",
                "week": 1,
                "fantasy_points_ppr": 12.0,
                "passing_interceptions": 0,
                "team": "KC",
                "opponent_team": "BAL",
            }
        ]
    )

    mock_nfl = MagicMock()
    mock_nfl.import_weekly_data.side_effect = legacy_error

    with (
        patch.dict(sys.modules, {"nfl_data_py": mock_nfl}),
        patch(
            "app.services.etl.fantasy.sync_player_analytics.pd.read_parquet",
            return_value=fallback_df,
        ) as read_parquet,
    ):
        weekly = _load_weekly_frame(2025)

    assert len(weekly) == 1
    assert weekly.iloc[0]["interceptions"] == 0
    assert weekly.iloc[0]["recent_team"] == "KC"
    mock_nfl.import_weekly_data.assert_called_once_with([2025])
    read_parquet.assert_called_once()
    assert "stats_player_week_2025.parquet" in read_parquet.call_args[0][0]


def test_load_snap_counts_frame_reads_parquet_release():
    from app.services.etl.fantasy.sync_player_analytics import _load_snap_counts_frame

    snap_df = pd.DataFrame(
        [
            {
                "week": 1,
                "pfr_player_id": "BarkSa00",
                "offense_pct": 0.75,
            }
        ]
    )

    with patch(
        "app.services.etl.fantasy.sync_player_analytics.pd.read_parquet",
        return_value=snap_df,
    ) as read_parquet:
        snaps = _load_snap_counts_frame(2025)

    assert len(snaps) == 1
    read_parquet.assert_called_once()
    assert "snap_counts_2025.parquet" in read_parquet.call_args[0][0]
