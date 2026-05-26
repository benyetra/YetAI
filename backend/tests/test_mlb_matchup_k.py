from datetime import date
from unittest.mock import MagicMock

from app.services.etl.mlb.profiles.matchup_k import (
    MatchupResult,
    batter_perf_from_profile,
    compute_lineup_k_matchup,
    pitcher_tensors_from_profile,
)


def test_pitcher_tensors_from_profile():
    profile = {
        "usage": {"FF": 0.6, "SL": 0.4},
        "location": {
            "FF": {
                "high_inside": 0.2,
                "low_outside": 0.5,
                "high_outside": 0.2,
                "low_inside": 0.1,
            },
        },
    }
    pitches, locs = pitcher_tensors_from_profile(profile)
    assert pitches["FF"]["usage_rate"] == 0.6
    assert locs["FF"]["low_outside"] == 0.5


def test_compute_lineup_k_matchup_from_snapshots():
    store = MagicMock()
    pitcher_snap = MagicMock()
    pitcher_snap.profile = {
        "usage": {"FF": 1.0},
        "location": {
            "FF": {
                "high_inside": 0.5,
                "low_outside": 0.5,
                "high_outside": 0.0,
                "low_inside": 0.0,
            }
        },
    }
    pitcher_snap.n_pitches = 300
    batter_snap = MagicMock()
    batter_snap.profile = {
        "whiff_by_pitch": {"FF": 0.35},
        "reliability_by_pitch": {"FF": 0.8},
        "cold_zones": {"FF": ["highInside"]},
    }
    batter_snap.n_pitches = 200
    store.get_pitcher.return_value = pitcher_snap
    store.get_batter.return_value = batter_snap

    result = compute_lineup_k_matchup(store, 1, [101], "R", date(2024, 6, 1))
    assert isinstance(result, MatchupResult)
    assert result.factor >= 0.0
    assert result.source in ("observed", "shrunk", "archetype", "league")


def test_batter_perf_from_profile_maps_zones():
    perf = batter_perf_from_profile(
        {
            "whiff_by_pitch": {"FF": 0.3},
            "reliability_by_pitch": {"FF": 0.6},
            "cold_zones": {"FF": ["high_inside"]},
        }
    )
    assert perf["FF"]["cold_zones"] == ["highInside"]
