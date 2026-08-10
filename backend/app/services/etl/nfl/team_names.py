"""Canonical NFL team names (Odds-API style) and alias normalization."""

from __future__ import annotations

# nflverse abbreviations and common aliases → full display names
_CANONICAL_BY_ABBR: dict[str, str] = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LA": "Los Angeles Rams",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders",
    "LAS": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
    "WSH": "Washington Commanders",
}

_CANONICAL_NAMES: frozenset[str] = frozenset(_CANONICAL_BY_ABBR.values())

_ALIAS_TO_CANONICAL: dict[str, str] = {
    **_CANONICAL_BY_ABBR,
    "LA Rams": "Los Angeles Rams",
    "LA Chargers": "Los Angeles Chargers",
    "NY Giants": "New York Giants",
    "NY Jets": "New York Jets",
    "Washington": "Washington Commanders",
    "Washington Football Team": "Washington Commanders",
    "Washington Redskins": "Washington Commanders",
    "Oakland Raiders": "Las Vegas Raiders",
}


def normalize_team_name(name: str) -> str:
    """Map nflverse/Odds aliases to canonical full team name."""
    stripped = name.strip()
    if not stripped:
        return stripped
    if stripped in _CANONICAL_NAMES:
        return stripped
    return _ALIAS_TO_CANONICAL.get(stripped, stripped)
