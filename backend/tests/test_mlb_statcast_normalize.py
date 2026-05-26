import pandas as pd

from app.services.etl.mlb.statcast_ingest.normalize import (
    bucket_zone,
    canonical_pitch_type,
    prune_statcast_columns,
)


def test_canonical_pitch_type_maps_four_seam():
    assert canonical_pitch_type("FF") == "FF"
    assert canonical_pitch_type("FA") == "FF"


def test_bucket_zone_high_inside():
    assert bucket_zone(-0.2, 3.8) == "high_inside"


def test_prune_keeps_required_columns():
    df = pd.DataFrame(
        {
            "game_date": ["2024-05-01"],
            "pitcher": [123],
            "batter": [456],
            "pitch_type": ["FF"],
            "plate_x": [0.1],
            "plate_z": [2.5],
            "p_throws": ["R"],
            "stand": ["L"],
            "description": ["swinging_strike"],
            "junk": [1],
        }
    )
    out = prune_statcast_columns(df)
    assert "junk" not in out.columns
    assert "zone_bucket" in out.columns
