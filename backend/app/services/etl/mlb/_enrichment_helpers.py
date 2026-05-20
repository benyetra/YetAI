"""Lightweight helpers for MLB enrichment tasks (no heavy imports)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# StatsAPI full names that differ from The Odds API labels
MLB_STATSAPI_TO_ODDS_TEAM: dict[str, str] = {
    "Athletics": "Oakland Athletics",
}


def flatten_batters(batters):
    if not batters:
        return []
    if isinstance(batters[0], dict):
        return batters
    return [batter for sublist in batters for batter in sublist]


def game_odds_key(game: dict) -> str:
    return f"{game['away_name']} @ {game['home_name']}"


def commence_date_et(commence_time: str) -> date | None:
    """Parse Odds API ISO time to the calendar date in US/Eastern."""
    if not commence_time:
        return None
    try:
        dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        return dt.astimezone(ET).date()
    except ValueError:
        return None


def teams_match(statsapi_name: str, odds_api_name: str) -> bool:
    if statsapi_name == odds_api_name:
        return True
    alias = MLB_STATSAPI_TO_ODDS_TEAM.get(statsapi_name, statsapi_name)
    if alias == odds_api_name:
        return True
    return statsapi_name in odds_api_name or odds_api_name in statsapi_name


def find_event_for_game(game: dict, events: list[dict]) -> dict | None:
    """Match a StatsAPI schedule row to an Odds API event (away/home)."""
    for event in events:
        if teams_match(game["away_name"], event.get("away_team", "")) and teams_match(
            game["home_name"], event.get("home_team", "")
        ):
            return event
    return None


def extract_h2h_prices(event: dict, preferred_bookmakers: tuple[str, ...]) -> dict:
    for bm in event.get("bookmakers", []):
        if bm.get("key") not in preferred_bookmakers:
            continue
        for market in bm.get("markets", []):
            if market.get("key") != "h2h":
                continue
            return {o["name"]: o["price"] for o in market.get("outcomes", [])}
    return {}


def match_team_price(team_name: str, prices: dict):
    """Map StatsAPI team name to Odds API h2h outcome price (fuzzy fallback)."""
    if team_name in prices:
        return prices[team_name], team_name
    alias = MLB_STATSAPI_TO_ODDS_TEAM.get(team_name)
    if alias and alias in prices:
        return prices[alias], alias
    parts = team_name.split()
    if len(parts) >= 2:
        short = " ".join(parts[-2:])
        for label, price in prices.items():
            if short in label or label in team_name:
                return price, label
    for label, price in prices.items():
        if label in team_name or team_name in label:
            return price, label
    return None, None
