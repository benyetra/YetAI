"""Three-way mapping between WNBA team identity spaces.

- WNBA_ID: integer team_id used by stats.wnba.com (nba_api with LeagueID=10)
- ESPN_ID: string team_id from site.api.espn.com WNBA endpoints
- NAME: canonical display name used in pred_wnba_* tables and shown in the UI

Both ID sets were live-verified on 2026-05-21:
- ESPN: http://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams
- WNBA: nba_api leaguedashteamstats with league_id_nullable="10", season="2025"

Toronto Tempo and Portland Fire are 2026 expansion teams. Their ESPN IDs were
live-verified 2026-05-21; stats.wnba.com WNBA IDs were verified 2026-05-22 via
nba_api LeagueDashTeamStats (league_id_nullable="10", season="2026").
"""

from __future__ import annotations

# Canonical WNBA team IDs (stats.wnba.com numeric IDs).
# Verified 2026-05-21 against the WNBA 2025 LeagueDashTeamStats dashboard.
WNBA_ID_TO_NAME: dict[int, str] = {
    1611661330: "Atlanta Dream",
    1611661329: "Chicago Sky",
    1611661323: "Connecticut Sun",
    1611661321: "Dallas Wings",
    1611661331: "Golden State Valkyries",
    1611661325: "Indiana Fever",
    1611661319: "Las Vegas Aces",
    1611661320: "Los Angeles Sparks",
    1611661324: "Minnesota Lynx",
    1611661313: "New York Liberty",
    1611661317: "Phoenix Mercury",
    1611661328: "Seattle Storm",
    1611661322: "Washington Mystics",
    1611661332: "Toronto Tempo",
    1611661327: "Portland Fire",
}

NAME_TO_WNBA_ID: dict[str, int] = {
    name.lower(): wnba_id for wnba_id, name in WNBA_ID_TO_NAME.items()
}

# ESPN team id (string) → WNBA team id. Live-verified 2026-05-21.
ESPN_TO_WNBA_TEAM_ID: dict[str, int] = {
    "20": 1611661330,      # Atlanta Dream
    "19": 1611661329,      # Chicago Sky
    "18": 1611661323,      # Connecticut Sun
    "3":  1611661321,      # Dallas Wings
    "129689": 1611661331,  # Golden State Valkyries (2025 expansion)
    "5":  1611661325,      # Indiana Fever
    "17": 1611661319,      # Las Vegas Aces
    "6":  1611661320,      # Los Angeles Sparks
    "8":  1611661324,      # Minnesota Lynx
    "9":  1611661313,      # New York Liberty
    "11": 1611661317,      # Phoenix Mercury
    "132052": 1611661327,  # Portland Fire (2026 expansion)
    "14": 1611661328,      # Seattle Storm
    "131935": 1611661332,  # Toronto Tempo (2026 expansion)
    "16": 1611661322,      # Washington Mystics
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
