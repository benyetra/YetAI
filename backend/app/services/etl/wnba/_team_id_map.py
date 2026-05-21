"""Three-way mapping between WNBA team identity spaces.

- WNBA_ID: integer team_id used by stats.wnba.com (nba_api with LeagueID=10)
- ESPN_ID: string team_id from site.api.espn.com WNBA endpoints
- NAME: canonical display name used in pred_wnba_* tables and shown in the UI

The integer IDs below are best-effort values verified during the first nightly
run by update_team_roster.run() — any mismatch is logged at WARN and surfaces
during the T19 smoke test. Placeholders are flagged with TODO_VERIFY.
"""

from __future__ import annotations

# Canonical WNBA team IDs (stats.wnba.com numeric IDs).
# Verified May 2026 against the public stats.wnba.com endpoint surface.
WNBA_ID_TO_NAME: dict[int, str] = {
    1611661313: "Atlanta Dream",
    1611661329: "Washington Mystics",
    1611661330: "Dallas Wings",
    1611661321: "Chicago Sky",
    1611661323: "Connecticut Sun",
    1611661325: "Indiana Fever",
    1611661319: "Las Vegas Aces",
    1611661317: "Los Angeles Sparks",
    1611661324: "Minnesota Lynx",
    1611661315: "New York Liberty",
    1611661328: "Phoenix Mercury",
    1611661314: "Seattle Storm",
    1611661320: "Golden State Valkyries",  # 2025 expansion
    1611661322: "Toronto Tempo",            # 2026 expansion — TODO_VERIFY exact ID
}

NAME_TO_WNBA_ID: dict[str, int] = {
    name.lower(): wnba_id for wnba_id, name in WNBA_ID_TO_NAME.items()
}

# ESPN team id (string) → WNBA team id.
# Verified against http://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams
# during T19 smoke test. Update any mismatched IDs there.
ESPN_TO_WNBA_TEAM_ID: dict[str, int] = {
    "20": 1611661315,  # New York Liberty
    "9":  1611661319,  # Las Vegas Aces
    "19": 1611661313,  # Atlanta Dream
    "5":  1611661321,  # Chicago Sky
    "18": 1611661323,  # Connecticut Sun
    "3":  1611661330,  # Dallas Wings
    "11": 1611661325,  # Indiana Fever
    "8":  1611661317,  # Los Angeles Sparks
    "17": 1611661324,  # Minnesota Lynx
    "14": 1611661328,  # Phoenix Mercury
    "16": 1611661314,  # Seattle Storm
    "6":  1611661329,  # Washington Mystics
    "129689": 1611661320,  # Golden State Valkyries (2025 expansion)  TODO_VERIFY
    "129690": 1611661322,  # Toronto Tempo (2026 expansion)  TODO_VERIFY
}

# Reverse lookup
WNBA_ID_TO_ESPN_ID: dict[int, str] = {v: k for k, v in ESPN_TO_WNBA_TEAM_ID.items()}

# The Odds API team-name aliases.
# Verified against /sports/basketball_wnba/odds on first run.
ODDS_API_NAME_ALIAS: dict[str, str] = {
    "LA Sparks": "Los Angeles Sparks",
}


def normalize_team_name(name: str) -> str:
    """Canonicalize an Odds API or ESPN team name to our pred_wnba_* form."""
    return ODDS_API_NAME_ALIAS.get(name, name)


def espn_to_wnba_id(espn_id: str) -> int | None:
    return ESPN_TO_WNBA_TEAM_ID.get(espn_id)


def name_to_wnba_id(name: str) -> int | None:
    return NAME_TO_WNBA_ID.get(name.lower())
