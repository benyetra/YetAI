from __future__ import annotations

import os


def get_ballpark_pal_api_key() -> str | None:
    key = (os.getenv("BALLPARK_PAL_API_KEY") or "").strip()
    return key or None


def ballpark_pal_enabled() -> bool:
    flag = os.getenv("BALLPARK_PAL_ENABLED", "0").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    return get_ballpark_pal_api_key() is not None


def _weight(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        w = float(raw)
    except ValueError:
        return default
    return max(0.0, min(1.0, w))


def bpp_game_prior_weight() -> float:
    return _weight("BPP_GAME_PRIOR_WEIGHT", 0.30)


def bpp_k_prior_weight() -> float:
    return _weight("BPP_K_PRIOR_WEIGHT", 0.25)


def bpp_hits_prior_weight() -> float:
    return _weight("BPP_HITS_PRIOR_WEIGHT", 0.25)


def bpp_hr_prior_weight() -> float:
    return _weight("BPP_HR_PRIOR_WEIGHT", 0.25)


def ballpark_pal_base_url() -> str:
    return (
        os.getenv("BALLPARK_PAL_BASE_URL") or "https://www.ballparkpal.com/api/v1"
    ).rstrip("/")
