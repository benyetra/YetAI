"""QB name → base passing-yards tier table (2026 REG calibrated).

Kept free of DB/nflverse imports so unit tests and training builders can use it
without loading the full ETL stack.

Tier predictions are **stable** (no hash-based week noise). Uncertainty is
expressed via prediction intervals and confidence, not fake yard variance.
"""

from __future__ import annotations

import os
from typing import Dict

# Base yards calibrated for 2026 REG depth charts (OurLads / Yahoo Aug 2026).
# Dual-threat QBs sit slightly lower on pure pass yards; pocket passers higher.
QB_YARDS_TIERS: dict[str, int] = {
    # Tier 1: Elite pass volume (270-295)
    "josh allen": 285,
    "patrick mahomes": 280,
    "joe burrow": 285,
    "justin herbert": 285,
    "dak prescott": 270,
    "jared goff": 265,
    # Tier 2: Strong starters (240-265)
    "jalen hurts": 255,
    "lamar jackson": 250,
    "baker mayfield": 255,
    "jordan love": 255,
    "matthew stafford": 255,
    "c.j. stroud": 255,
    "trevor lawrence": 250,
    "brock purdy": 250,
    "geno smith": 245,
    "sam darnold": 245,
    "bo nix": 245,
    "drake maye": 245,
    "tua tagovailoa": 240,
    "kyler murray": 240,
    "kirk cousins": 235,
    "aaron rodgers": 230,
    "daniel jones": 230,
    # Tier 3: Developing / new starters (200-235)
    "caleb williams": 240,
    "jayden daniels": 225,
    "michael penix": 235,
    "michael penix jr.": 235,
    "michael penix jr": 235,
    "bryce young": 220,
    "jacoby brissett": 210,
    "jaxson dart": 210,
    "malik willis": 205,
    "cam ward": 200,
    "tyler shough": 195,
    "shedeur sanders": 190,
    "anthony richardson": 195,
    "jj mccarthy": 205,
    "j.j. mccarthy": 205,
    "spencer rattler": 185,
    # Backups / depth
    "tyler huntley": 185,
    "joe flacco": 200,
    "mac jones": 195,
    "aidan o'connell": 185,
    "drew lock": 185,
    "mason rudolph": 185,
    "gardner minshew": 200,
    "jameis winston": 210,
    "marcus mariota": 190,
    "kenny pickett": 185,
    "davis mills": 185,
    "jarrett stidham": 180,
    "tanner mckee": 180,
    "cooper rush": 185,
    "brandon allen": 175,
    "will levis": 185,
    "russell wilson": 220,
}

_DEFAULT_BASE_YARDS = 210
_TRUTHY = frozenset({"1", "true", "yes"})


def normalize_qb_name_key(qb_name: str) -> str:
    key = qb_name.lower().strip()
    return (
        key.replace(" jr.", "")
        .replace(" jr", "")
        .replace(" ii", "")
        .replace(" sr.", "")
        .replace(" sr", "")
        .strip()
    )


def lookup_tier_base_yards(qb_name: str) -> int:
    key = normalize_qb_name_key(qb_name)
    return int(
        QB_YARDS_TIERS.get(key)
        or QB_YARDS_TIERS.get(qb_name.lower().strip(), _DEFAULT_BASE_YARDS)
    )


def _tier_uncertainty(base_yards: float) -> tuple[float, float, float]:
    """Return (half_width, base_confidence, interval_pad)."""
    if base_yards >= 270:
        return 28.0, 0.82, 35.0
    if base_yards >= 240:
        return 32.0, 0.75, 40.0
    if base_yards >= 210:
        return 36.0, 0.68, 45.0
    return 40.0, 0.60, 50.0


def _legacy_hash_variance_enabled() -> bool:
    """Opt-in only — default is stable tiers (no seeded yard noise)."""
    return os.getenv("NFL_QB_TIER_HASH_VARIANCE", "").strip().lower() in _TRUTHY


def predict_qb_passing_yards(
    qb_name: str,
    season: int,
    week: int,
    is_backup: bool = False,
    *,
    injury_status: str | None = None,
) -> Dict:
    """
    Predict QB passing yards from the name tier table.

    Stable by default: predicted yards == tier base (backup/injury adjusted).
    Set ``NFL_QB_TIER_HASH_VARIANCE=1`` to restore legacy seeded week noise.
    """
    base_yards = float(lookup_tier_base_yards(qb_name))
    status = (injury_status or "").strip().lower()

    if is_backup:
        base_yards = max(150.0, base_yards - 25.0)
    elif status in {"questionable", "q"}:
        # Soft downgrade: expect fewer dropbacks / conservative game plan
        base_yards = max(150.0, base_yards - 12.0)

    half_width, base_confidence, _ = _tier_uncertainty(base_yards)

    if is_backup:
        base_confidence = max(0.45, base_confidence - 0.15)
    elif status in {"questionable", "q"}:
        base_confidence = max(0.45, base_confidence - 0.10)
    elif status in {"out", "ir", "doubtful"}:
        base_confidence = max(0.40, base_confidence - 0.20)

    predicted_yards = base_yards
    if _legacy_hash_variance_enabled():
        import hashlib

        seed = int(
            hashlib.md5(f"{qb_name}_{season}_{week}".encode()).hexdigest()[:8], 16
        )
        variance_range = int(half_width)
        variance = (seed % (variance_range * 2 + 1)) - variance_range
        predicted_yards = max(150.0, min(350.0, base_yards + variance))

    predicted_yards = round(max(150.0, min(350.0, predicted_yards)), 1)
    lower = round(max(120.0, predicted_yards - half_width), 1)
    upper = round(min(380.0, predicted_yards + half_width), 1)

    if is_backup:
        method = "dynamic_backup"
    elif status in {"questionable", "q"}:
        method = "dynamic_questionable"
    else:
        method = "dynamic_starter"

    return {
        "predicted_passing_yards": predicted_yards,
        "confidence": round(base_confidence, 3),
        "prediction_method": method,
        "tier_base_yards": float(base_yards),
        "prediction_interval_lower": lower,
        "prediction_interval_upper": upper,
        "injury_status": injury_status or "Healthy",
    }
