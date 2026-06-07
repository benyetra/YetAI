"""Tests for fantasy player_analytics mapping audit."""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.services.etl.fantasy.sync_player_analytics import (
    audit_player_analytics_mapping,
)


@pytest.mark.asyncio
async def test_audit_player_analytics_mapping_reports_skip_rate():
    db = MagicMock()
    db.query.return_value.filter.return_value.count.return_value = 500

    weekly = pd.DataFrame(
        [
            {"player_id": "gsis-1", "week": 1},
            {"player_id": "gsis-2", "week": 1},
            {"player_id": "gsis-3", "week": 1},
        ]
    )

    with (
        patch(
            "app.services.etl.fantasy.sync_player_analytics._build_gsis_to_fantasy_player_map",
            AsyncMock(return_value={"gsis-1": 1, "gsis-2": 2}),
        ),
        patch(
            "app.services.etl.fantasy.sync_player_analytics.fantasy_sleeper_unified.sleeper._get_all_players",
            AsyncMock(return_value={"1": {}, "2": {}, "3": {}}),
        ),
        patch(
            "app.services.etl.fantasy.sync_player_analytics._load_weekly_frame",
            return_value=weekly,
        ),
    ):
        report = await audit_player_analytics_mapping(db, season=2025)

    assert report["fantasy_players_mapped"] == 2
    assert report["nflverse_weekly_rows"] == 3
    assert report["rows_mappable"] == 2
    assert report["rows_skipped_unmapped"] == 1
    assert report["skip_rate_pct"] == pytest.approx(33.3, abs=0.1)
