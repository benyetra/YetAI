import logging
from datetime import date, datetime, timedelta

import requests
import statsapi

from app.services.etl.mlb.mlb_batter_analysis import fetch_batter_performance_vs_pitches
from app.services.etl.mlb.mlb_pitcher_analysis import fetch_pitcher_data
from app.services.etl.mlb.profiles.constants import mlb_profiles_enabled
from app.services.etl.mlb.profiles.matchup_k import (
    batter_perf_from_profile,
    pitcher_tensors_from_profile,
)

logger = logging.getLogger(__name__)


def fetch_last_start_date(pitcher_id):
    """
    Return the date of the pitcher’s most recent start this season.
    Falls back to 7 days ago if we can’t fetch anything.
    """
    try:
        data = statsapi.player_stat_data(
            pitcher_id, group="pitching", type="gameLog"  # no season filter here
        )
        splits = data.get("stats", [{}])[0].get("splits", [])

        # Keep only this season’s starts
        this_year = str(datetime.today().year)
        start_dates = [
            split["date"]
            for split in splits
            if split.get("stat", {}).get("gamesStarted", 0) > 0
            and split.get("date", "").startswith(this_year)
        ]

        if start_dates:
            last_date = max(start_dates)
            return datetime.strptime(last_date, "%Y-%m-%d").date()

    except Exception as e:
        print(f"Warning: could not fetch last start for {pitcher_id}: {e}")

    # fallback: assume rested 7 days
    return datetime.today().date() - timedelta(days=7)


def _pitcher_hand(pitcher_id: int) -> str:
    url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}"
    try:
        data = requests.get(url, timeout=15).json()
        if data.get("people"):
            return data["people"][0].get("pitchHand", {}).get("code", "R")
    except Exception as exc:
        logger.warning("pitcher hand fetch %s: %s", pitcher_id, exc)
    return "R"


def matchup_adjusted_strikeouts(
    pitcher_id,
    batter_id,
    as_of_date: date | None = None,
    db=None,
):
    """
    Adjusts strikeout projections based on pitch mix vs batter weaknesses.
    Uses ProfileStore when MLB_PROFILES_ENABLED.
    """
    as_of = as_of_date or date.today()
    pitcher_hand = _pitcher_hand(pitcher_id)

    if mlb_profiles_enabled():
        try:
            from app.core.database import SessionLocal
            from app.services.etl.mlb.profiles.profile_store import ProfileStore

            session = db
            own = False
            if session is None and SessionLocal is not None:
                session = SessionLocal()
                own = True
            if session is not None:
                store = ProfileStore(session)
                ps = store.get_pitcher(pitcher_id, as_of)
                bs = store.get_batter(batter_id, pitcher_hand, as_of)
                if ps and ps.profile and bs and bs.profile:
                    pitcher_pitches, pitcher_locations = pitcher_tensors_from_profile(
                        ps.profile
                    )
                    batter_performance = batter_perf_from_profile(bs.profile)
                    factor = _matchup_factor_from_tensors(
                        pitcher_pitches, pitcher_locations, batter_performance
                    )
                    if own:
                        session.close()
                    return factor
                if own:
                    session.close()
        except Exception as exc:
            logger.warning("profile matchup_adjusted_strikeouts: %s", exc)

    pitcher_pitches, pitcher_locations = fetch_pitcher_data(pitcher_id)
    batter_performance = fetch_batter_performance_vs_pitches(batter_id, pitcher_hand)
    return _matchup_factor_from_tensors(
        pitcher_pitches, pitcher_locations, batter_performance
    )


def _matchup_factor_from_tensors(
    pitcher_pitches, pitcher_locations, batter_performance
):
    strikeout_factor = 0.0
    for pitch, stats in pitcher_pitches.items():
        if pitch not in batter_performance:
            continue
        bp = batter_performance[pitch]
        whiff_rate_weight = bp.get("whiff_rate", 0.0) * 0.5
        location_advantage = 0.0
        locs = pitcher_locations.get(pitch, {})
        total = sum(locs.values()) or 1
        hi_pct = locs.get("high_inside", 0) / total * 100
        lo_pct = locs.get("low_outside", 0) / total * 100
        cold = bp.get("cold_zones", []) or []
        if hi_pct > 30 and "highInside" in cold:
            location_advantage += 0.15
        if lo_pct > 30 and "lowOutside" in cold:
            location_advantage += 0.15
        usage = stats.get("usage_rate", 0.0) if isinstance(stats, dict) else 0.0
        strikeout_factor += (whiff_rate_weight + location_advantage) * usage
    return round(strikeout_factor, 2)
