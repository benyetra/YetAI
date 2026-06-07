"""Tests for GSIS mapping fallback via nflverse import_ids."""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.services.etl.fantasy.sync_player_analytics import (
    _build_gsis_to_fantasy_player_map,
    _load_nflverse_sleeper_to_gsis,
)


def test_load_nflverse_sleeper_to_gsis_maps_gibbs():
    ids_df = pd.DataFrame(
        [
            {
                "name": "Jahmyr Gibbs",
                "gsis_id": "00-0039139",
                "sleeper_id": 9221.0,
            },
            {
                "name": "Saquon Barkley",
                "gsis_id": "00-0034844",
                "sleeper_id": 4866.0,
            },
        ]
    )
    mock_nfl = MagicMock()
    mock_nfl.import_ids.return_value = ids_df

    with patch.dict("sys.modules", {"nfl_data_py": mock_nfl}):
        mapping = _load_nflverse_sleeper_to_gsis()

    assert mapping["9221"] == "00-0039139"
    assert mapping["4866"] == "00-0034844"


@pytest.mark.asyncio
async def test_build_gsis_map_uses_nflverse_when_sleeper_missing_gsis():
    db = MagicMock()
    fantasy_row = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [(99, "9221")]

    sleeper_players = {
        "9221": {
            "first_name": "Jahmyr",
            "last_name": "Gibbs",
            "gsis_id": None,
        }
    }
    nflverse_map = {"9221": "00-0039139"}

    with (
        patch(
            "app.services.etl.fantasy.sync_player_analytics.fantasy_sleeper_unified.sleeper._get_all_players",
            AsyncMock(return_value=sleeper_players),
        ),
        patch(
            "app.services.etl.fantasy.sync_player_analytics._load_nflverse_sleeper_to_gsis",
            return_value=nflverse_map,
        ),
    ):
        gsis_to_fantasy = await _build_gsis_to_fantasy_player_map(db)

    assert gsis_to_fantasy["00-0039139"] == 99
