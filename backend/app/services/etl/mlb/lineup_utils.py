# scripts/mlb/lineup_utils.py  (FULL REPLACEMENT, 3.8/3.9 compatible)

from typing import Optional, List
from datetime import datetime
import statsapi

# If these imports fail in your env, keep the try/except fallbacks.
try:
    from mlb_pitcher_analysis import fetch_pitcher_data as fetch_pitch_data
except Exception:
    fetch_pitch_data = None

try:
    from mlb_batter_analysis import fetch_batter_performance_vs_pitches
except Exception:
    fetch_batter_performance_vs_pitches = None


def projected_lineup(team_id: int) -> List[int]:
    """Fallback projected lineup: first 9 active players."""
    try:
        roster = statsapi.get("team_roster", {"teamId": team_id, "rosterType": "active"})["roster"]
        return [p["person"]["id"] for p in roster[:9]]
    except Exception:
        return []


def batter_k_rate_vs_hand(batter_id: int, hand_code: str, season: Optional[str] = None) -> float:
    """
    Approx strikeout rate (K per AB) vs pitcher hand. hand_code: 'R' or 'L'.
    """
    if season is None:
        season = str(datetime.today().year)
    sit_code = "vr" if hand_code.upper().startswith("R") else "vl"
    try:
        data = statsapi.get(
            "people",
            {
                "personIds": batter_id,
                "hydrate": f"stats(group=[hitting],type=[season],gameType=R,season={season},sitCodes={sit_code})",
            },
        )
        s = data["people"][0]["stats"][0]["splits"][0]["stat"]
        ab = float(s.get("atBats", 0) or 0.0)
        k  = float(s.get("strikeOuts", 0) or 0.0)
        return (k / ab) if ab > 0 else 0.20
    except Exception:
        return 0.20  # safe fallback


def lineup_k_rate_vs_hand(team_id: int, pitcher_hand_code: str) -> Optional[float]:
    """Average K% vs the pitcher's hand across the projected lineup (fraction, e.g. 0.22)."""
    ids = projected_lineup(team_id)
    if not ids:
        return None
    vals = [batter_k_rate_vs_hand(bid, pitcher_hand_code) for bid in ids]
    return (sum(vals) / len(vals)) if vals else None


def lineup_matchup_adjusted_strikeouts(pitcher_id: int, batter_ids: List[int], pitcher_hand_code: str) -> float:
    """
    Lineup-weighted matchup factor using pitch-type whiffs + location cold zones.
    """
    if not batter_ids:
        return 0.0

    pitcher_pitches, pitcher_locations = {}, {}
    if fetch_pitch_data is not None:
        try:
            pitcher_pitches, pitcher_locations = fetch_pitch_data(pitcher_id)
        except Exception:
            pitcher_pitches, pitcher_locations = {}, {}
    if not pitcher_pitches:
        return 0.0

    perf_by_batter = {}
    if fetch_batter_performance_vs_pitches is not None:
        for bid in batter_ids:
            try:
                perf_by_batter[bid] = fetch_batter_performance_vs_pitches(bid, pitcher_hand_code)
            except Exception:
                perf_by_batter[bid] = {}

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

    return round(strikeout_factor, 2)
