# shared/team_mapping.py

import statsapi

# Canonical mapping: full team names or abbreviations → park_id (3-letter lowercase code)
TEAM_TO_PARK_ID = {
    "ARI": "ari",
    "Arizona Diamondbacks": "ari",
    "ATL": "atl",
    "Atlanta Braves": "atl",
    "BAL": "bal",
    "Baltimore Orioles": "bal",
    "BOS": "bos",
    "Boston Red Sox": "bos",
    "CHC": "chc",
    "Chicago Cubs": "chc",
    "CWS": "cws",
    "Chicago White Sox": "cws",
    "CIN": "cin",
    "Cincinnati Reds": "cin",
    "CLE": "cle",
    "Cleveland Guardians": "cle",
    "COL": "col",
    "Colorado Rockies": "col",
    "DET": "det",
    "Detroit Tigers": "det",
    "HOU": "hou",
    "Houston Astros": "hou",
    "KC": "kc",
    "Kansas City Royals": "kc",
    "LAA": "ana",
    "Los Angeles Angels": "ana",
    "LAD": "lad",
    "Los Angeles Dodgers": "lad",
    "MIA": "mia",
    "Miami Marlins": "mia",
    "MIL": "mil",
    "Milwaukee Brewers": "mil",
    "MIN": "min",
    "Minnesota Twins": "min",
    "NYM": "nym",
    "New York Mets": "nym",
    "NYY": "nyy",
    "New York Yankees": "nyy",
    "OAK": "oak",
    "Athletics": "oak",
    "PHI": "phi",
    "Philadelphia Phillies": "phi",
    "PIT": "pit",
    "Pittsburgh Pirates": "pit",
    "SD": "sd",
    "San Diego Padres": "sd",
    "SF": "sf",
    "San Francisco Giants": "sf",
    "SEA": "sea",
    "Seattle Mariners": "sea",
    "STL": "stl",
    "St. Louis Cardinals": "stl",
    "TB": "tb",
    "Tampa Bay Rays": "tb",
    "TEX": "tex",
    "Texas Rangers": "tex",
    "TOR": "tor",
    "Toronto Blue Jays": "tor",
    "WAS": "was",
    "Washington Nationals": "was",
}


def resolve_park_id(team_name: str) -> str:
    """
    Normalize any team name or abbreviation to the canonical 3-letter park_id.
    Returns None if the team can't be mapped.
    """
    if not team_name or not isinstance(team_name, str):
        return None

    team_name = team_name.strip()
    if team_name.upper() in TEAM_TO_PARK_ID:
        return TEAM_TO_PARK_ID[team_name.upper()]
    if team_name.title() in TEAM_TO_PARK_ID:
        return TEAM_TO_PARK_ID[team_name.title()]

    # Try API fallback for obscure labels
    try:
        team = statsapi.lookup_team(team_name)
        if team:
            return TEAM_TO_PARK_ID.get(team[0].get("abbreviation"))
    except Exception:
        pass

    return None
