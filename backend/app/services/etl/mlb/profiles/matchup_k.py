"""Strikeout matchup tensors from ProfileStore snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.services.etl.mlb.profiles.constants import (
    LEAGUE_WHIFF_BY_PITCH,
    PITCH_TYPES,
    PROFILE_VERSION,
    SHRINKAGE_K_WHIFF,
)
from app.services.etl.mlb.profiles.profile_store import ProfileStore

MatchupSource = Literal["observed", "shrunk", "archetype", "league", "legacy_api"]


@dataclass(frozen=True)
class MatchupResult:
    factor: float
    source: MatchupSource


def _zone_key_to_cold(zone: str) -> str:
    """Map profile zone_bucket keys to legacy cold_zone names."""
    mapping = {
        "high_inside": "highInside",
        "high_outside": "highOutside",
        "low_inside": "lowInside",
        "low_outside": "lowOutside",
    }
    return mapping.get(zone, zone)


def pitcher_tensors_from_profile(profile: dict) -> tuple[dict, dict]:
    """Convert snapshot JSON to legacy pitcher_pitches / pitcher_locations shape."""
    usage = profile.get("usage") or {}
    location = profile.get("location") or {}
    pitcher_pitches: dict = {}
    pitcher_locations: dict = {}
    for pt, rate in usage.items():
        pitcher_pitches[pt] = {"usage_rate": float(rate)}
        locs = location.get(pt, {})
        pitcher_locations[pt] = {
            "high_inside": float(locs.get("high_inside", 0.0)),
            "high_outside": float(locs.get("high_outside", 0.0)),
            "low_inside": float(locs.get("low_inside", 0.0)),
            "low_outside": float(locs.get("low_outside", 0.0)),
        }
    return pitcher_pitches, pitcher_locations


def batter_perf_from_profile(profile: dict) -> dict:
    """Per pitch-type batter performance for matchup loop."""
    whiff = profile.get("whiff_by_pitch") or {}
    reliability = profile.get("reliability_by_pitch") or {}
    cold = profile.get("cold_zones") or {}
    out: dict = {}
    for pt in set(whiff) | set(cold):
        rel = float(reliability.get(pt, 0.0))
        if rel >= 0.5:
            source = "observed"
        elif rel > 0:
            source = "shrunk"
        else:
            source = "league"
        zones = cold.get(pt, []) or []
        out[pt] = {
            "whiff_rate": float(whiff.get(pt, LEAGUE_WHIFF_BY_PITCH.get(pt, 0.25))),
            "cold_zones": [_zone_key_to_cold(z) for z in zones],
            "_source": source,
        }
    return out


def _league_archetype_batter() -> dict:
    out = {}
    for pt in PITCH_TYPES:
        out[pt] = {
            "whiff_rate": LEAGUE_WHIFF_BY_PITCH.get(pt, 0.25),
            "cold_zones": [],
            "_source": "archetype",
        }
    return out


def _dominant_source(sources: list[str]) -> MatchupSource:
    if not sources:
        return "league"
    priority = ("observed", "shrunk", "archetype", "league", "legacy_api")
    for p in priority:
        if p in sources:
            return p  # type: ignore[return-value]
    return "league"


def compute_lineup_k_matchup(
    store: ProfileStore,
    pitcher_id: int,
    batter_ids: list[int],
    pitcher_hand: str,
    as_of_date: date,
    window: str = "season",
) -> MatchupResult:
    """Lineup-weighted K matchup factor from profile snapshots."""
    if not batter_ids:
        return MatchupResult(0.0, "league")

    ps = store.get_pitcher(pitcher_id, as_of_date, window=window)
    if not ps or not ps.profile:
        return MatchupResult(0.0, "league")

    pitcher_pitches, pitcher_locations = pitcher_tensors_from_profile(ps.profile)
    if not pitcher_pitches:
        return MatchupResult(0.0, "league")

    sources: list[str] = []
    if ps.n_pitches >= SHRINKAGE_K_WHIFF:
        sources.append("observed")
    elif ps.n_pitches > 0:
        sources.append("shrunk")
    else:
        sources.append("league")

    perf_by_batter: dict[int, dict] = {}
    for bid in batter_ids:
        snap = store.get_batter(bid, pitcher_hand, as_of_date, window=window)
        if snap and snap.profile:
            perf_by_batter[bid] = batter_perf_from_profile(snap.profile)
            for pt_data in perf_by_batter[bid].values():
                if isinstance(pt_data, dict) and "_source" in pt_data:
                    sources.append(pt_data["_source"])
        else:
            perf_by_batter[bid] = _league_archetype_batter()
            sources.append("archetype")

    w = 1.0 / len(batter_ids)
    strikeout_factor = 0.0

    for pitch, pstats in pitcher_pitches.items():
        usage = pstats.get("usage_rate", 0.0)
        locs = pitcher_locations.get(pitch, {})
        total = float(sum(locs.values())) or 1.0
        hi_pct = (locs.get("high_inside", 0.0) / total) * 100.0
        lo_pct = (locs.get("low_outside", 0.0) / total) * 100.0

        whiff_weight_avg = 0.0
        loc_adv_avg = 0.0

        for bid in batter_ids:
            bp = perf_by_batter.get(bid, {}).get(pitch)
            if not bp:
                continue
            whiff_weight_avg += (bp.get("whiff_rate", 0.0) * 0.5) * w
            cold_zones = bp.get("cold_zones", []) or []
            location_adv = 0.0
            if hi_pct > 30 and "highInside" in cold_zones:
                location_adv += 0.15
            if lo_pct > 30 and "lowOutside" in cold_zones:
                location_adv += 0.15
            loc_adv_avg += location_adv * w

        strikeout_factor += (whiff_weight_avg + loc_adv_avg) * usage

    return MatchupResult(round(strikeout_factor, 2), _dominant_source(sources))
