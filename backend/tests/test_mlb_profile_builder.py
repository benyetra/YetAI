from datetime import date

import pandas as pd

from app.services.etl.mlb.profiles.profile_builder import (
    aggregate_batter,
    aggregate_pitcher,
)


def _synthetic_pitches(n: int = 500) -> pd.DataFrame:
    rows = []
    pitchers = [101, 102]
    batters = [201, 202]
    for i in range(n):
        rows.append(
            {
                "game_date": date(2024, 5, 1 + (i % 20)),
                "pitcher": pitchers[i % 2],
                "batter": batters[i % 2],
                "pitch_type_canon": "FF" if i % 3 else "SL",
                "zone_bucket": "high_inside" if i % 2 else "low_outside",
                "p_throws": "R",
                "stand": "L",
                "is_whiff": i % 5 == 0,
            }
        )
    return pd.DataFrame(rows)


def test_aggregate_pitcher_usage_sums():
    df = _synthetic_pitches()
    as_of = date(2024, 6, 1)
    prof = aggregate_pitcher(df, 101, "season", as_of)
    assert prof is not None
    assert abs(sum(prof["usage"].values()) - 1.0) < 0.01
    assert prof["n_pitches"] > 0


def test_aggregate_batter_whiff_shrunk():
    df = _synthetic_pitches()
    as_of = date(2024, 6, 1)
    prof = aggregate_batter(df, 201, "R", "season", as_of)
    assert prof is not None
    assert "whiff_by_pitch" in prof
    assert "FF" in prof["whiff_by_pitch"] or "SL" in prof["whiff_by_pitch"]
