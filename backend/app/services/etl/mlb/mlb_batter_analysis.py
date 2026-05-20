import requests


def fetch_batter_performance_vs_pitches(batter_id, pitcher_hand, season=None):
    """
    Fetches a batter's performance against different pitch types and locations,
    considering the pitcher's handedness.
    """
    if season is None:
        from datetime import datetime

        season = str(datetime.today().year)
    url = f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats"
    params = {"stats": "hitting", "group": "hitting", "season": season, "gameType": "R"}
    response = requests.get(url, params=params)
    data = response.json()

    pitch_performance = {}

    if "people" in data and data["people"]:
        stats = data["people"][0].get("stats", [])
        if stats:
            # Check if pitchData exists to avoid KeyErrors
            hitting_data = stats[0]["splits"][0]["stat"].get("pitchData", [])

            for pitch in hitting_data:
                pitch_type = pitch.get("pitchType", "Unknown")

                # Iterate over batter splits to find performance against the specific pitcher hand
                for split in stats[0]["splits"]:
                    handedness_data = split.get("handedness", {})
                    if handedness_data.get("pitchHand") == pitcher_hand:
                        pitch_performance[pitch_type] = {
                            "batting_avg": split.get("battingAverage", 0),
                            "slugging": split.get("sluggingPercentage", 0),
                            "whiff_rate": split.get("whiffPercentage", 0),
                            "hot_zones": split.get("hotZone", {}),
                            "cold_zones": split.get("coldZone", {}),
                        }

    return pitch_performance
