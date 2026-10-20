"""ESPN scoreboard helpers shared by NBA ETL services.

ESPN's public scoreboard endpoint is the source of truth for which games happened
and which teams played. ESPN returns its own team IDs; we map to NBA.com IDs
because the rest of the prediction schema (TeamRoster, RecentGames, …) keys on
NBA.com IDs.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Iterable
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)

EASTERN = ZoneInfo("America/New_York")

# Static map: ESPN team id (string) → NBA.com team id.
# Verified against http://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams
ESPN_TO_NBA_TEAM_ID: dict[str, int] = {
    "1": 1610612737,  # Atlanta Hawks
    "2": 1610612738,  # Boston Celtics
    "3": 1610612740,  # New Orleans Pelicans
    "4": 1610612741,  # Chicago Bulls
    "5": 1610612739,  # Cleveland Cavaliers
    "6": 1610612742,  # Dallas Mavericks
    "7": 1610612743,  # Denver Nuggets
    "8": 1610612765,  # Detroit Pistons
    "9": 1610612744,  # Golden State Warriors
    "10": 1610612745,  # Houston Rockets
    "11": 1610612754,  # Indiana Pacers
    "12": 1610612746,  # LA Clippers
    "13": 1610612747,  # Los Angeles Lakers
    "14": 1610612748,  # Miami Heat
    "15": 1610612749,  # Milwaukee Bucks
    "16": 1610612750,  # Minnesota Timberwolves
    "17": 1610612751,  # Brooklyn Nets
    "18": 1610612752,  # New York Knicks
    "19": 1610612753,  # Orlando Magic
    "20": 1610612755,  # Philadelphia 76ers
    "21": 1610612756,  # Phoenix Suns
    "22": 1610612757,  # Portland Trail Blazers
    "23": 1610612758,  # Sacramento Kings
    "24": 1610612759,  # San Antonio Spurs
    "25": 1610612760,  # Oklahoma City Thunder
    "26": 1610612762,  # Utah Jazz
    "27": 1610612764,  # Washington Wizards
    "28": 1610612761,  # Toronto Raptors
    "29": 1610612763,  # Memphis Grizzlies
    "30": 1610612766,  # Charlotte Hornets
}

# NBA.com team_id → display name. Sourced from YetiBets/utilities/data/nba_teams.json;
# small enough to embed and avoid shipping a data file with the service.
NBA_TEAM_NAMES: dict[int, str] = {
    1610612737: "Atlanta Hawks",
    1610612738: "Boston Celtics",
    1610612739: "Cleveland Cavaliers",
    1610612740: "New Orleans Pelicans",
    1610612741: "Chicago Bulls",
    1610612742: "Dallas Mavericks",
    1610612743: "Denver Nuggets",
    1610612744: "Golden State Warriors",
    1610612745: "Houston Rockets",
    1610612746: "Los Angeles Clippers",
    1610612747: "Los Angeles Lakers",
    1610612748: "Miami Heat",
    1610612749: "Milwaukee Bucks",
    1610612750: "Minnesota Timberwolves",
    1610612751: "Brooklyn Nets",
    1610612752: "New York Knicks",
    1610612753: "Orlando Magic",
    1610612754: "Indiana Pacers",
    1610612755: "Philadelphia 76ers",
    1610612756: "Phoenix Suns",
    1610612757: "Portland Trail Blazers",
    1610612758: "Sacramento Kings",
    1610612759: "San Antonio Spurs",
    1610612760: "Oklahoma City Thunder",
    1610612761: "Toronto Raptors",
    1610612762: "Utah Jazz",
    1610612763: "Memphis Grizzlies",
    1610612764: "Washington Wizards",
    1610612765: "Detroit Pistons",
    1610612766: "Charlotte Hornets",
}


def fetch_games_for_date(target_date: date | None = None) -> list[dict]:
    """Fetch NBA games for a given date from ESPN's scoreboard.

    target_date=None hits the live scoreboard (ESPN's "today"). Otherwise we
    pass ?dates=YYYYMMDD. Returns a list of `{home_team_id, away_team_id,
    home_team_name, away_team_name}` dicts using NBA.com team ids — games whose
    ESPN team ids don't map to NBA.com (G-League, exhibition, etc.) are dropped.
    """
    params = {"dates": target_date.strftime("%Y%m%d")} if target_date else None
    response = requests.get(ESPN_SCOREBOARD, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    games: list[dict] = []
    for event in data.get("events", []) or []:
        competitions = event.get("competitions") or [{}]
        competitors = competitions[0].get("competitors") or []
        if len(competitors) != 2:
            continue

        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not (home and away):
            continue

        home_nba = ESPN_TO_NBA_TEAM_ID.get(home["team"]["id"])
        away_nba = ESPN_TO_NBA_TEAM_ID.get(away["team"]["id"])
        if not (home_nba and away_nba):
            continue

        games.append(
            {
                "home_team_id": home_nba,
                "away_team_id": away_nba,
                "home_team_name": home["team"]["displayName"],
                "away_team_name": away["team"]["displayName"],
            }
        )
    return games


# ESPN season types that count as real games: regular season, playoffs, play-in.
# Preseason (1) and the All-Star break (4) are excluded.
COMPETITIVE_SEASON_TYPES = frozenset({2, 3, 5})


def parse_final_scores(data: dict) -> list[dict]:
    """Completed competitive games from an ESPN scoreboard payload.

    Team names come from NBA_TEAM_NAMES (the Odds API spelling that
    pred_nba_game_lines uses), not ESPN's "LA Clippers" display name.
    """
    finals: list[dict] = []
    for event in data.get("events", []) or []:
        if (event.get("season") or {}).get("type") not in COMPETITIVE_SEASON_TYPES:
            continue
        competition = (event.get("competitions") or [{}])[0]
        if not ((competition.get("status") or {}).get("type") or {}).get("completed"):
            continue
        sides = {c.get("homeAway"): c for c in competition.get("competitors") or []}
        home, away = sides.get("home"), sides.get("away")
        if not (home and away):
            continue
        home_id = ESPN_TO_NBA_TEAM_ID.get(str(home["team"]["id"]))
        away_id = ESPN_TO_NBA_TEAM_ID.get(str(away["team"]["id"]))
        if not (home_id and away_id):
            continue
        try:
            home_score, away_score = int(home["score"]), int(away["score"])
        except (KeyError, TypeError, ValueError):
            continue
        finals.append(
            {
                "home_team_name": NBA_TEAM_NAMES[home_id],
                "away_team_name": NBA_TEAM_NAMES[away_id],
                "home_score": home_score,
                "away_score": away_score,
            }
        )
    return finals


def fetch_final_scores(target_date: date) -> list[dict]:
    """parse_final_scores for one Eastern calendar date."""
    response = requests.get(
        ESPN_SCOREBOARD,
        params={"dates": target_date.strftime("%Y%m%d")},
        timeout=15,
    )
    response.raise_for_status()
    return parse_final_scores(response.json())


ESPN_TEAM_ROSTER = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{}/roster"
)


def fetch_team_rosters() -> dict[int, list[str]]:
    """Current ESPN roster per team: NBA.com team_id -> player full names.

    ESPN reflects signings, trades and waivers the same day, so it is the
    tie-breaker for which team a player is on. Teams whose roster call fails
    are omitted; callers should check coverage before trusting the result.
    """
    rosters: dict[int, list[str]] = {}
    for espn_id, nba_team_id in ESPN_TO_NBA_TEAM_ID.items():
        try:
            response = requests.get(ESPN_TEAM_ROSTER.format(espn_id), timeout=10)
            response.raise_for_status()
            athletes = response.json().get("athletes") or []
        except (requests.RequestException, ValueError) as exc:
            logger.warning("ESPN roster fetch failed for team %s: %s", espn_id, exc)
            continue
        names = [a.get("fullName") for a in athletes if a.get("fullName")]
        if names:
            rosters[nba_team_id] = names
    return rosters


def build_matchups(games: Iterable[dict]) -> tuple[set[int], dict[int, int]]:
    """From fetch_games_for_date output, return (set of team_ids, team→opponent map)."""
    team_ids: set[int] = set()
    matchups: dict[int, int] = {}
    for g in games:
        h, a = g["home_team_id"], g["away_team_id"]
        team_ids.update((h, a))
        matchups[h] = a
        matchups[a] = h
    return team_ids, matchups


def now_eastern() -> datetime:
    return datetime.now(EASTERN)
