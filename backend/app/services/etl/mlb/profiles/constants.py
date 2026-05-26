import os

PROFILE_VERSION = "mlb-profile-v1"

PITCH_TYPES = ("FF", "SI", "FC", "SL", "CH", "CU", "KC", "FS", "ST", "UNK")

ZONE_KEYS = ("high_inside", "high_outside", "low_inside", "low_outside")

WINDOWS = ("7d", "30d", "season", "3yr_decay")

PITCH_TYPE_MAP = {
    "FF": "FF",
    "FA": "FF",
    "FT": "SI",
    "SI": "SI",
    "FC": "FC",
    "SL": "SL",
    "CH": "CH",
    "CU": "CU",
    "KC": "KC",
    "FS": "FS",
    "ST": "ST",
}

LEAGUE_WHIFF_BY_PITCH = {
    "FF": 0.22,
    "SI": 0.20,
    "FC": 0.24,
    "SL": 0.32,
    "CH": 0.30,
    "CU": 0.28,
    "KC": 0.27,
    "FS": 0.29,
    "ST": 0.31,
    "UNK": 0.25,
}

SHRINKAGE_K_WHIFF = 200


def mlb_profiles_enabled() -> bool:
    # Default off until Statcast backfill + profile rebuild are verified in prod.
    return os.getenv("MLB_PROFILES_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
