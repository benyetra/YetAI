import requests

def fetch_pitcher_data(pitcher_id, season=None):
    """
    Fetches pitch usage rates, velocities, spin rates, and location tendencies for a pitcher.
    """
    if season is None:
        from datetime import datetime
        season = str(datetime.today().year)
    url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats?group=pitching&stats=gameLog"
    params = {
        "stats": "pitching",
        "group": "pitching",
        "season": season,
        "gameType": "R"
    }
    response = requests.get(url, params=params)
    data = response.json()

    pitch_types = {}
    pitch_locations = {}

    if "people" in data and data["people"]:
        stats = data["people"][0].get("stats", [])
        if stats:
            pitching_data = stats[0]["splits"][0]["stat"].get("pitchData", [])

            for pitch in pitching_data:
                pitch_type = pitch["pitchType"]
                pitch_types[pitch_type] = {
                    "usage_rate": pitch["percentage"],
                    "velocity": pitch.get("averageSpeed", 0),
                    "spin_rate": pitch.get("spinRate", 0)
                }

                pitch_locations[pitch_type] = {
                    "high_inside": pitch.get("location", {}).get("highInside", 0),
                    "high_outside": pitch.get("location", {}).get("highOutside", 0),
                    "low_inside": pitch.get("location", {}).get("lowInside", 0),
                    "low_outside": pitch.get("location", {}).get("lowOutside", 0)
                }


    return pitch_types, pitch_locations
