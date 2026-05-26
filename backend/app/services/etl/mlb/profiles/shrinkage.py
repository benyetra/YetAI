from app.services.etl.mlb.profiles.constants import (
    LEAGUE_WHIFF_BY_PITCH,
    SHRINKAGE_K_WHIFF,
)


def reliability(n: int, k: float = SHRINKAGE_K_WHIFF) -> float:
    n = max(0, int(n))
    return n / (n + k) if (n + k) > 0 else 0.0


def posterior_whiff_rate(
    observed: float, n_pitches: int, pitch_type: str
) -> tuple[float, float]:
    prior = LEAGUE_WHIFF_BY_PITCH.get(pitch_type, 0.25)
    rel = reliability(n_pitches, SHRINKAGE_K_WHIFF)
    post = rel * observed + (1 - rel) * prior
    return post, rel
