import pandas as pd
from unittest.mock import patch

from app.services.etl.mlb.statcast_ingest.backfill import backfill_month


@patch("app.services.etl.mlb.statcast_ingest.backfill._fetch_statcast")
def test_backfill_month_writes_parquet(mock_fetch, tmp_path, monkeypatch):
    monkeypatch.setenv("MLB_STATCAST_S3_PREFIX", str(tmp_path))
    mock_fetch.return_value = pd.DataFrame(
        {
            "game_date": ["2024-05-15"],
            "pitcher": [1],
            "batter": [2],
            "pitch_type": ["FF"],
            "plate_x": [0.0],
            "plate_z": [2.5],
            "p_throws": ["R"],
            "stand": ["L"],
            "description": ["swinging_strike"],
        }
    )
    uri = backfill_month(2024, 5, force=False)
    assert uri is not None
