from __future__ import annotations

import pandas as pd

from app.services.etl.mlb.profiles.constants import PITCH_TYPE_MAP

KEEP_COLUMNS = [
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "batter",
    "pitch_type",
    "release_speed",
    "release_spin_rate",
    "plate_x",
    "plate_z",
    "p_throws",
    "stand",
    "description",
    "events",
    "estimated_woba_using_speedangle",
]


def canonical_pitch_type(code: str | None) -> str:
    if not code:
        return "UNK"
    return PITCH_TYPE_MAP.get(str(code).upper(), "UNK")


def bucket_zone(plate_x: float, plate_z: float) -> str:
    """Map plate coordinates to four zones (matches mlb_pitcher_analysis buckets)."""
    x, z = float(plate_x), float(plate_z)
    high = z >= 2.5
    inside = x <= 0.0
    if high and inside:
        return "high_inside"
    if high and not inside:
        return "high_outside"
    if not high and inside:
        return "low_inside"
    return "low_outside"


def is_whiff(description: str | None) -> bool:
    if not description:
        return False
    d = description.lower()
    return "swinging_strike" in d or d in {"swinging_strike_blocked"}


def prune_statcast_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in KEEP_COLUMNS if c in df.columns]
    out = df[cols].copy()
    out["game_date"] = pd.to_datetime(out["game_date"]).dt.date
    out["pitch_type_canon"] = out["pitch_type"].map(canonical_pitch_type)
    out["zone_bucket"] = [
        bucket_zone(x, z)
        for x, z in zip(out["plate_x"].fillna(0), out["plate_z"].fillna(2.5))
    ]
    out["is_whiff"] = out["description"].map(is_whiff)
    return out
