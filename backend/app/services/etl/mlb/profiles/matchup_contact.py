"""Contact-quality matchup scores from batter profile tensors (Phase 4)."""

from __future__ import annotations

from datetime import date

from app.services.etl.mlb.profiles.constants import PITCH_TYPES
from app.services.etl.mlb.profiles.profile_store import ProfileStore

LEAGUE_XWOBA = 0.320
LEAGUE_ISO = 0.165
LEAGUE_BARREL = 0.08


def contact_matchup_score(
    store: ProfileStore,
    batter_id: int,
    pitcher_id: int,
    vs_hand: str,
    as_of_date: date,
    window: str = "season",
) -> tuple[float, str | None]:
    """
    Batter contact quality vs pitcher usage mix.
    Returns (score_delta, profile_version) — delta applied to combined_score scale.
    """
    batter = store.get_batter(batter_id, vs_hand, as_of_date, window=window)
    pitcher = store.get_pitcher(pitcher_id, as_of_date, window=window)
    if not batter or not pitcher or not batter.profile or not pitcher.profile:
        return 0.0, None

    usage = pitcher.profile.get("usage") or {}
    xwoba = batter.profile.get("xwoba_by_pitch") or {}
    iso = batter.profile.get("iso_by_pitch") or {}
    barrel = batter.profile.get("barrel_rate_by_pitch") or {}

    version = getattr(batter, "profile_version", None)
    if not usage:
        return 0.0, version

    contact_edge = 0.0
    for pt, u in usage.items():
        if u <= 0:
            continue
        bx = float(xwoba.get(pt, LEAGUE_XWOBA))
        bi = float(iso.get(pt, LEAGUE_ISO))
        bb = float(barrel.get(pt, LEAGUE_BARREL))
        contact_edge += float(u) * (
            (bx - LEAGUE_XWOBA) * 2.0 + (bi - LEAGUE_ISO) + (bb - LEAGUE_BARREL)
        )

    delta = max(-0.5, min(0.5, contact_edge))
    return round(delta, 3), version


def lineup_contact_delta(
    store: ProfileStore,
    batter_ids: list[int],
    pitcher_id: int,
    vs_hand: str,
    as_of_date: date,
    window: str = "season",
) -> tuple[float, str | None]:
    if not batter_ids:
        return 0.0, None
    deltas = []
    version = None
    for bid in batter_ids:
        d, v = contact_matchup_score(
            store, bid, pitcher_id, vs_hand, as_of_date, window
        )
        deltas.append(d)
        version = version or v
    return round(sum(deltas) / len(deltas), 3), version
