import requests
import statsapi
from datetime import datetime, timedelta
from mlb_pitcher_analysis import fetch_pitcher_data
from mlb_batter_analysis import fetch_batter_performance_vs_pitches

def fetch_last_start_date(pitcher_id):
    """
    Return the date of the pitcher’s most recent start this season.
    Falls back to 7 days ago if we can’t fetch anything.
    """
    try:
        data = statsapi.player_stat_data(
            pitcher_id,
            group="pitching",
            type="gameLog"        # no season filter here
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


def matchup_adjusted_strikeouts(pitcher_id, batter_id):
    """
    Adjusts strikeout projections based on how a pitcher’s pitch mix matches up
    against a batter’s strengths/weaknesses.
    """
    # Fetch pitcher's pitch data
    pitcher_pitches, pitcher_locations = fetch_pitcher_data(pitcher_id)

    # Retrieve pitcher handedness
    url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}"
    resp = requests.get(url)
    data = resp.json()

    if "people" in data and data["people"]:
        pitcher_hand = data["people"][0] \
            .get("pitchHand", {}) \
            .get("code", "R")
    else:
        print(f"Warning: Unable to fetch pitcher handedness for {pitcher_id}")
        pitcher_hand = "R"

    # Batter performance vs. that hand
    batter_performance = fetch_batter_performance_vs_pitches(
        batter_id, pitcher_hand
    )

    strikeout_factor = 0.0

    for pitch, stats in pitcher_pitches.items():
        if pitch not in batter_performance:
            continue

        bp = batter_performance[pitch]
        whiff_rate_weight = bp["whiff_rate"] * 0.5
        location_advantage = 0.0

        total = sum(pitcher_locations[pitch].values()) or 1
        hi_pct = pitcher_locations[pitch]["high_inside"] / total * 100
        lo_pct = pitcher_locations[pitch]["low_outside"] / total * 100

        if hi_pct > 30 and "highInside" in bp["cold_zones"]:
            location_advantage += 0.15
        if lo_pct > 30 and "lowOutside" in bp["cold_zones"]:
            location_advantage += 0.15

        strikeout_factor += (whiff_rate_weight + location_advantage) \
                             * stats["usage_rate"]

    return round(strikeout_factor, 2)
