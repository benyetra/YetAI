"""
NHL Daily Predictions Generator
Generates goalie save predictions for today's games with Fanatics lines integration
"""

import sys
import os

from app.services.etl.nhl._db import db_session
from app.models.predictions_models import (
    NHLGoaliePredictions,
    NHLGoalie,
    NHLTeamStats,
    NHLTeam,
)
from app.services.etl.nhl.nhl_api_client import NHLAPIClient
from datetime import datetime, date
import time
import logging

# Configuration
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "icehockey_nhl"

# One event-odds response includes all NHL prop markets we need (1 credit vs 3).
_NHL_EVENT_ODDS_MARKETS = "player_total_saves,player_shots_on_goal,totals"
_NHL_EVENT_ODDS_CACHE_TTL_SECONDS = 600
_nhl_event_odds_cache: dict = (
    {}
)  # (event_id, markets) -> (expires_at_monotonic, payload)

# Global dict to store Fanatics lines
FANATICS_LINES = {}


def clear_nhl_event_odds_cache() -> None:
    """Drop memoized NHL event-odds payloads (tests / run boundaries)."""
    _nhl_event_odds_cache.clear()


def _fetch_nhl_event_odds_payload(
    event_id: str, markets: str = _NHL_EVENT_ODDS_MARKETS
) -> dict:
    """Return DraftKings event odds (memoized per event + markets)."""
    cache_key = (event_id, markets)
    entry = _nhl_event_odds_cache.get(cache_key)
    if entry is not None:
        expires_at, payload = entry
        if time.monotonic() < expires_at:
            return payload
        _nhl_event_odds_cache.pop(cache_key, None)

    if not ODDS_API_KEY:
        return {}

    from app.services.odds_api_sync import sync_odds_get

    url = f"{ODDS_API_BASE}/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": markets,
        "bookmakers": "draftkings",
        "oddsFormat": "american",
    }
    resp = sync_odds_get(
        url,
        params=params,
        caller=f"etl.nhl.event_odds.{event_id}",
        timeout=10,
        raise_for_status=False,
    )
    if resp is None or resp.status_code != 200:
        return {}
    data = resp.json()
    _nhl_event_odds_cache[cache_key] = (
        time.monotonic() + _NHL_EVENT_ODDS_CACHE_TTL_SECONDS,
        data,
    )
    return data


# Setup logging
logging.basicConfig(level=logging.INFO)

# ============================================================================
# THE ODDS API INTEGRATION
# ============================================================================

# Team name mapping: NHL API name -> Odds API name
NHL_TO_ODDS_API_TEAMS = {
    "Anaheim": "Anaheim Ducks",
    "Arizona": "Arizona Coyotes",
    "Boston": "Boston Bruins",
    "Buffalo": "Buffalo Sabres",
    "Calgary": "Calgary Flames",
    "Carolina": "Carolina Hurricanes",
    "Chicago": "Chicago Blackhawks",
    "Colorado": "Colorado Avalanche",
    "Columbus": "Columbus Blue Jackets",
    "Dallas": "Dallas Stars",
    "Detroit": "Detroit Red Wings",
    "Edmonton": "Edmonton Oilers",
    "Florida": "Florida Panthers",
    "Los Angeles": "Los Angeles Kings",
    "Minnesota": "Minnesota Wild",
    "Montréal": "Montréal Canadiens",
    "Montreal": "Montréal Canadiens",
    "Nashville": "Nashville Predators",
    "New Jersey": "New Jersey Devils",
    "New York": "New York Islanders",  # Default to Islanders
    "Ottawa": "Ottawa Senators",
    "Philadelphia": "Philadelphia Flyers",
    "Pittsburgh": "Pittsburgh Penguins",
    "San José": "San Jose Sharks",
    "San Jose": "San Jose Sharks",
    "Seattle": "Seattle Kraken",
    "St. Louis": "St Louis Blues",
    "Tampa Bay": "Tampa Bay Lightning",
    "Toronto": "Toronto Maple Leafs",
    "Vancouver": "Vancouver Canucks",
    "Vegas": "Vegas Golden Knights",
    "Washington": "Washington Capitals",
    "Winnipeg": "Winnipeg Jets",
    "Utah": "Utah Mammoth",
}


# Handle special cases for NY teams
def resolve_ny_team(team_abbrev):
    """Resolve New York team based on abbreviation"""
    if team_abbrev == "NYR":
        return "New York Rangers"
    elif team_abbrev == "NYI":
        return "New York Islanders"
    return "New York Islanders"  # Default


def get_odds_api_team_name(nhl_team_name, team_abbrev=""):
    """Convert NHL API team name to Odds API team name"""
    # Special handling for New York teams
    if "New York" in nhl_team_name or nhl_team_name == "New York":
        return resolve_ny_team(team_abbrev)

    # Look up in mapping
    return NHL_TO_ODDS_API_TEAMS.get(nhl_team_name, nhl_team_name)


def get_nhl_events_from_odds_api():
    """
    Fetch today's NHL events from The Odds API
    Returns: list of events with event IDs
    """
    from app.services.odds_api_sync import sync_odds_get

    url = f"{ODDS_API_BASE}/sports/{SPORT}/events"
    params = {"apiKey": ODDS_API_KEY, "regions": "us", "bookmakers": "draftkings"}

    try:
        response = sync_odds_get(
            url,
            params=params,
            caller="etl.nhl.events",
            timeout=10,
            raise_for_status=True,
        )
        if response is None:
            return []
        all_events = response.json()

        # Don't filter by date - return all events
        # The NHL schedule endpoint already filters to today's games
        logging.info(f"Found {len(all_events)} NHL events from Odds API")

        # Debug: log first few events
        for i, event in enumerate(all_events[:5]):
            logging.info(
                f"  Event {i+1}: {event.get('away_team')} @ {event.get('home_team')} at {event.get('commence_time')}"
            )

        return all_events

    except Exception as e:
        logging.error(f"Error fetching NHL events from Odds API: {e}")
        return []


def get_goalie_saves_odds_for_event(
    event_id, home_team, away_team, markets=_NHL_EVENT_ODDS_MARKETS
):
    """
    Fetch goalie save lines from The Odds API for a specific event

    Args:
        event_id: The Odds API event ID
        home_team: Home team name
        away_team: Away team name
        markets: Odds API markets to request (the refresh passes saves only)

    Returns:
        dict mapping goalie names to their lines
    """
    try:
        data = _fetch_nhl_event_odds_payload(event_id, markets)
        if not data:
            logging.warning(
                "No Odds API payload for goalie saves %s @ %s", away_team, home_team
            )
            return {}

        goalie_lines = {}

        # Parse bookmakers
        for bookmaker in data.get("bookmakers", []):
            # Only use DraftKings
            if bookmaker.get("key") != "draftkings":
                continue

            for market in bookmaker.get("markets", []):
                if market.get("key") != "player_total_saves":
                    continue

                # Process outcomes (each goalie has Over/Under)
                outcomes_by_goalie = {}
                for outcome in market.get("outcomes", []):
                    goalie_name = outcome.get("description", "")
                    over_under = outcome.get("name", "")  # 'Over' or 'Under'
                    line = outcome.get("point")
                    odds = outcome.get("price")

                    # Convert decimal odds to American
                    if isinstance(odds, float):
                        if odds >= 2.0:
                            american_odds = int((odds - 1) * 100)
                        else:
                            american_odds = int(-100 / (odds - 1))
                    else:
                        american_odds = odds

                    if goalie_name not in outcomes_by_goalie:
                        outcomes_by_goalie[goalie_name] = {"line": line}

                    if over_under == "Over":
                        outcomes_by_goalie[goalie_name]["over_odds"] = american_odds
                    elif over_under == "Under":
                        outcomes_by_goalie[goalie_name]["under_odds"] = american_odds

                # Store complete lines
                for goalie_name, line_data in outcomes_by_goalie.items():
                    if (
                        "line" in line_data
                        and "over_odds" in line_data
                        and "under_odds" in line_data
                    ):
                        goalie_lines[goalie_name] = {
                            "line": line_data["line"],
                            "over_odds": line_data["over_odds"],
                            "under_odds": line_data["under_odds"],
                            "available": True,
                        }
                        logging.info(
                            f"DraftKings line for {goalie_name}: O/U {line_data['line']} ({line_data['over_odds']}/{line_data['under_odds']})"
                        )

        return goalie_lines

    except Exception as e:
        logging.error(f"Error fetching goalie saves odds: {e}")
        return {}


def get_player_shots_odds_for_event(event_id, home_team, away_team):
    """
    Fetch player shots on goal lines from The Odds API for a specific event

    Args:
        event_id: The Odds API event ID
        home_team: Home team name
        away_team: Away team name

    Returns:
        dict mapping player names to their lines
    """
    try:
        data = _fetch_nhl_event_odds_payload(event_id)
        if not data:
            logging.warning(
                "No Odds API payload for player shots %s @ %s", away_team, home_team
            )
            return {}

        player_lines = {}

        # Parse bookmakers
        for bookmaker in data.get("bookmakers", []):
            if bookmaker.get("key") != "draftkings":
                continue

            for market in bookmaker.get("markets", []):
                if market.get("key") != "player_shots_on_goal":
                    continue

                # Process outcomes (each player has Over/Under)
                outcomes_by_player = {}
                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description", "")
                    over_under = outcome.get("name", "")
                    line = outcome.get("point")
                    odds = outcome.get("price")

                    if player_name not in outcomes_by_player:
                        outcomes_by_player[player_name] = {"line": line}

                    if over_under == "Over":
                        outcomes_by_player[player_name]["over_odds"] = odds
                    elif over_under == "Under":
                        outcomes_by_player[player_name]["under_odds"] = odds

                # Store complete lines
                for player_name, line_data in outcomes_by_player.items():
                    if "line" in line_data:
                        player_lines[player_name] = {
                            "line": line_data["line"],
                            "over_odds": line_data.get("over_odds"),
                            "under_odds": line_data.get("under_odds"),
                        }

        return player_lines

    except Exception as e:
        logging.error(f"Error fetching player shots odds: {e}")
        return {}


def get_team_totals_odds_for_event(event_id, home_team, away_team):
    """
    Fetch team totals (over/under) lines from The Odds API for a specific event

    Args:
        event_id: The Odds API event ID
        home_team: Home team name
        away_team: Away team name

    Returns:
        dict with totals line and odds
    """
    try:
        data = _fetch_nhl_event_odds_payload(event_id)
        if not data:
            logging.warning(
                "No Odds API payload for totals %s @ %s", away_team, home_team
            )
            return {}

        totals_data = {}

        # Parse bookmakers
        for bookmaker in data.get("bookmakers", []):
            if bookmaker.get("key") != "draftkings":
                continue

            for market in bookmaker.get("markets", []):
                if market.get("key") != "totals":
                    continue

                # Get Over/Under outcomes
                for outcome in market.get("outcomes", []):
                    over_under = outcome.get("name", "")
                    line = outcome.get("point")
                    odds = outcome.get("price")

                    if "line" not in totals_data:
                        totals_data["line"] = line

                    if over_under == "Over":
                        totals_data["over_odds"] = odds
                    elif over_under == "Under":
                        totals_data["under_odds"] = odds

        return totals_data

    except Exception as e:
        logging.error(f"Error fetching team totals odds: {e}")
        return {}


def fetch_all_fanatics_lines(games):
    """
    Fetch DraftKings goalie save lines for all today's games

    Args:
        games: List of NHL games from NHL API

    Returns:
        dict mapping goalie names to their DraftKings lines
    """
    global FANATICS_LINES

    if not ODDS_API_KEY:
        logging.warning("ODDS_API_KEY not set - cannot fetch DraftKings lines")
        return {}

    print("\n" + "=" * 80)
    print("🔍 FETCHING DRAFTKINGS LINES FROM THE ODDS API")
    print("=" * 80)

    # Get today's events from Odds API
    odds_events = get_nhl_events_from_odds_api()

    if not odds_events:
        print("⚠ No events found from Odds API")
        return {}

    # Create lookup: NHL team name -> Odds API event ID
    event_lookup = {}
    for event in odds_events:
        # Match format: "Away @ Home"
        key = f"{event['away_team']} @ {event['home_team']}"
        event_lookup[key] = event["id"]

    # Fetch lines for each game
    lines_fetched = 0
    for game in games:
        home_team = game.get("homeTeam", {})
        away_team = game.get("awayTeam", {})

        # NHL API uses different team names - convert to Odds API format
        nhl_home = home_team.get("placeName", {}).get("default", "")
        nhl_away = away_team.get("placeName", {}).get("default", "")
        home_abbrev = home_team.get("abbrev", "")
        away_abbrev = away_team.get("abbrev", "")

        # Convert to Odds API team names
        odds_home = get_odds_api_team_name(nhl_home, home_abbrev)
        odds_away = get_odds_api_team_name(nhl_away, away_abbrev)

        # Build matchup key
        matchup_key = f"{odds_away} @ {odds_home}"
        event_id = event_lookup.get(matchup_key)

        if not event_id:
            logging.warning(
                f"Could not match NHL game to Odds API: {nhl_away} @ {nhl_home} (tried: {matchup_key})"
            )
            continue

        # Fetch goalie lines for this event
        print(f"\n📊 Fetching lines for {nhl_away} @ {nhl_home}...")
        goalie_lines = get_goalie_saves_odds_for_event(event_id, nhl_home, nhl_away)

        if goalie_lines:
            FANATICS_LINES.update(goalie_lines)
            lines_fetched += len(goalie_lines)
            print(f"   ✓ Found {len(goalie_lines)} goalie line(s)")
        else:
            print(f"   ⚠ No Fanatics lines available")

        time.sleep(0.5)  # Rate limiting

    print("\n" + "=" * 80)
    print(f"✓ Fetched {lines_fetched} DraftKings goalie save lines")
    print("=" * 80)

    return FANATICS_LINES


def manual_line_input_mode():
    """
    Interactive mode to manually input lines from Fanatics
    Use this when you want to enter lines during script execution
    """
    global FANATICS_LINES

    print("\n" + "=" * 80)
    print("📱 MANUAL LINE ENTRY MODE")
    print("=" * 80)
    print("Open Fanatics app/website and enter goalie save lines manually")
    print("Enter 'done' when finished, 'skip' to use file/default lines")
    print()

    while True:
        goalie_name = input("Enter goalie name (or 'done'/'skip'): ").strip()

        if goalie_name.lower() in ["done", "skip"]:
            break

        try:
            line = float(input(f"  Enter O/U line for {goalie_name} (e.g., 26.5): "))
            over_odds = int(input(f"  Enter OVER odds (e.g., -110): "))
            under_odds = int(input(f"  Enter UNDER odds (e.g., -110): "))

            FANATICS_LINES[goalie_name] = {
                "line": line,
                "over_odds": over_odds,
                "under_odds": under_odds,
                "available": True,
            }

            print(f"  ✓ Saved: {goalie_name} O/U {line} ({over_odds}/{under_odds})")
            print()

        except ValueError:
            print("  ⚠ Invalid input, try again")
            continue

    return len(FANATICS_LINES) > 0


def load_fanatics_lines_from_file(filename="fanatics_lines_today.txt"):
    """
    Load Fanatics lines from a text file

    File format (one per line):
    Goalie Name | Line | Over Odds | Under Odds
    Connor Hellebuyck | 28.5 | -110 | -110
    Sergei Bobrovsky | 26.5 | -115 | -105
    """
    global FANATICS_LINES

    try:
        with open(filename, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = [p.strip() for p in line.split("|")]
                if len(parts) == 4:
                    name, o_u_line, over_odds, under_odds = parts
                    FANATICS_LINES[name] = {
                        "line": float(o_u_line),
                        "over_odds": int(over_odds),
                        "under_odds": int(under_odds),
                        "available": True,
                    }

        print(f"✓ Loaded {len(FANATICS_LINES)} Fanatics lines from {filename}")
        return True
    except FileNotFoundError:
        print(f"⚠ No Fanatics lines file found ({filename})")
        print(f"  Create {filename} with format:")
        print(f"  Goalie Name | Line | Over Odds | Under Odds")
        return False
    except Exception as e:
        print(f"⚠ Error loading Fanatics lines: {e}")
        return False


def save_lines_to_file(filename="fanatics_lines_today.txt"):
    """Save manually entered lines to file for future use"""
    global FANATICS_LINES

    if not FANATICS_LINES:
        return

    try:
        with open(filename, "w") as f:
            f.write("# Fanatics Goalie Save Lines\n")
            f.write("# Format: Goalie Name | Line | Over Odds | Under Odds\n")
            f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %I:%M %p')}\n\n")

            for name, data in FANATICS_LINES.items():
                f.write(
                    f"{name} | {data['line']} | {data['over_odds']} | {data['under_odds']}\n"
                )

        print(f"✓ Saved {len(FANATICS_LINES)} lines to {filename}")
    except Exception as e:
        print(f"⚠ Error saving lines: {e}")


def get_todays_games():
    """Fetch today's NHL schedule - ONLY games happening today"""
    client = NHLAPIClient()
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"📅 Fetching NHL schedule for {today}...")
    schedule = client.get_schedule(today)

    if not schedule or "gameWeek" not in schedule:
        print("⚠ No games found")
        return []

    games = []
    for game_week in schedule["gameWeek"]:
        # Filter to only games on today's date
        if game_week.get("date") == today:
            for game in game_week.get("games", []):
                # Only regular season or playoff games
                if game.get("gameType") in [2, 3]:
                    games.append(game)

    return games


def get_starting_goalie_from_game(game_id):
    """
    Try to get starting goalies from game boxscore
    Note: Starting goalies may not be announced until ~1 hour before game
    """
    client = NHLAPIClient()

    try:
        boxscore = client.get_game_boxscore(game_id)

        if not boxscore:
            return None, None

        # Get goalies
        home_goalies = (
            boxscore.get("playerByGameStats", {}).get("homeTeam", {}).get("goalies", [])
        )
        away_goalies = (
            boxscore.get("playerByGameStats", {}).get("awayTeam", {}).get("goalies", [])
        )

        # Find starting goalies
        home_starter = next((g for g in home_goalies if g.get("starter")), None)
        away_starter = next((g for g in away_goalies if g.get("starter")), None)

        return home_starter, away_starter
    except:
        return None, None


def get_likely_starters_from_roster(team_abbrev):
    """
    Get likely starting goalies from team roster
    Fallback if starters not announced yet
    """
    client = NHLAPIClient()

    try:
        roster = client.get_team_roster(team_abbrev)

        if not roster:
            return []

        goalies = []
        for position_group in ["goalies", "forwards", "defensemen"]:
            for player in roster.get(position_group, []):
                if player.get("positionCode") == "G":
                    goalies.append(
                        {
                            "id": player["id"],
                            "name": f"{player.get('firstName', {}).get('default', '')} {player.get('lastName', {}).get('default', '')}",
                            "number": player.get("sweaterNumber"),
                        }
                    )

        return goalies
    except:
        return []
