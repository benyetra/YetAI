"""
Player Props Service for fetching and managing player proposition bets.

This service handles fetching player props from The Odds API for:
- NFL, NBA, NHL, MLB
- Currently limited to FanDuel for API quota savings
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from app.services.odds_api_service import OddsAPIService, OddsFormat

logger = logging.getLogger(__name__)


# Player prop markets available for each sport
# Reference: https://the-odds-api.com/sports-odds-data/betting-markets.html
PLAYER_PROP_MARKETS = {
    "americanfootball_nfl": [
        "player_pass_tds",  # Passing touchdowns
        "player_pass_yds",  # Passing yards
        "player_pass_completions",  # Pass completions
        "player_pass_attempts",  # Pass attempts
        "player_pass_interceptions",  # Interceptions thrown
        "player_pass_longest_completion",  # Longest completion
        "player_rush_yds",  # Rushing yards
        "player_rush_attempts",  # Rush attempts
        "player_rush_longest",  # Longest rush
        "player_receptions",  # Receptions
        "player_reception_yds",  # Receiving yards
        "player_reception_longest",  # Longest reception
        "player_kicking_points",  # Kicker points
        "player_field_goals",  # Field goals made
        "player_tackles_assists",  # Tackles + Assists
        "player_1st_td",  # First touchdown scorer
        "player_last_td",  # Last touchdown scorer
        "player_anytime_td",  # Anytime touchdown scorer
    ],
    "basketball_nba": [
        "player_points",  # Points scored
        "player_rebounds",  # Total rebounds
        "player_assists",  # Assists
        "player_threes",  # 3-pointers made
        "player_blocks",  # Blocks
        "player_steals",  # Steals
        "player_turnovers",  # Turnovers
        "player_points_rebounds_assists",  # Points + Rebounds + Assists
        "player_points_rebounds",  # Points + Rebounds
        "player_points_assists",  # Points + Assists
        "player_rebounds_assists",  # Rebounds + Assists
        "player_blocks_steals",  # Blocks + Steals
        "player_double_double",  # Double double
        "player_triple_double",  # Triple double
    ],
    "icehockey_nhl": [
        "player_points",  # Points (Goals + Assists)
        "player_assists",  # Assists
        "player_shots_on_goal",  # Shots on goal
        "player_blocked_shots",  # Blocked shots
        "player_goalie_saves",  # Goalie saves
        "player_goalie_shutout",  # Goalie shutout
        "player_power_play_points",  # Power play points
        "player_anytime_goal_scorer",  # Anytime goal scorer
        "player_first_goal",  # First goal scorer
    ],
    "baseball_mlb": [
        "player_hits",  # Hits
        "player_total_bases",  # Total bases
        "player_runs",  # Runs scored
        "player_rbis",  # RBIs
        "player_home_runs",  # Home runs
        "player_stolen_bases",  # Stolen bases
        "player_strikeouts",  # Batter strikeouts
        "player_pitcher_strikeouts",  # Pitcher strikeouts
        "player_hits_allowed",  # Hits allowed (pitcher)
        "player_walks",  # Walks (batter)
        "player_pitcher_walks",  # Walks allowed (pitcher)
        "player_earned_runs",  # Earned runs (pitcher)
        "player_outs",  # Outs pitched
    ],
}


class PlayerPropsService:
    """Service for fetching and parsing player prop betting markets"""

    def __init__(self, odds_api_service: OddsAPIService):
        """
        Initialize with odds API service

        Args:
            odds_api_service: Instance of OddsAPIService
        """
        self.odds_api = odds_api_service

    async def get_player_props_for_event(
        self,
        sport: str,
        event_id: str,
        markets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch player props for a specific event

        Args:
            sport: Sport key (e.g., 'americanfootball_nfl')
            event_id: The odds API event ID
            markets: List of specific markets to fetch. If None, fetches all available for the sport.

        Returns:
            Dictionary with event info and organized player props by market
        """
        # Get available markets for this sport
        available_markets = PLAYER_PROP_MARKETS.get(sport, [])

        if not available_markets:
            logger.warning(f"No player prop markets configured for sport: {sport}")
            return {"error": f"Sport {sport} not supported for player props"}

        # Use specified markets or all available
        markets_to_fetch = markets if markets else available_markets

        # Join markets into comma-separated string
        markets_str = ",".join(markets_to_fetch)

        logger.info(
            f"Fetching player props for {sport} event {event_id}, markets: {markets_str}"
        )

        try:
            # Fetch from Odds API - limit to FanDuel only to save API quota
            event_data = await self.odds_api.get_event_odds(
                sport=sport,
                event_id=event_id,
                regions="us",
                markets=markets_str,
                odds_format=OddsFormat.AMERICAN,
                bookmakers="fanduel",  # Only FanDuel to save API calls
            )

            if not event_data:
                return {"error": "Event not found"}

            # Parse and organize the player props
            props_by_market = self._organize_props_by_market(event_data)

            return {
                "event_id": event_data.id,
                "sport_key": event_data.sport_key,
                "sport_title": event_data.sport_title,
                "commence_time": event_data.commence_time.isoformat(),
                "home_team": event_data.home_team,
                "away_team": event_data.away_team,
                "markets": props_by_market,
            }

        except Exception as e:
            logger.error(f"Error fetching player props for event {event_id}: {e}")
            raise

    def _organize_props_by_market(self, event_data: Any) -> Dict[str, Any]:
        """
        Organize player props by market type

        Args:
            event_data: Game object from odds API

        Returns:
            Dictionary organized by market with player props
        """
        markets_dict = {}

        # FanDuel should be the only bookmaker since we filtered
        for bookmaker in event_data.bookmakers:
            if bookmaker.key != "fanduel":
                continue

            for market in bookmaker.markets:
                market_key = market["key"]

                # Initialize market if not exists
                if market_key not in markets_dict:
                    markets_dict[market_key] = {
                        "market_key": market_key,
                        "last_update": bookmaker.last_update.isoformat(),
                        "players": {},
                    }

                # Group outcomes by player (description field contains player name)
                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description", "Unknown")
                    over_under = outcome.get("name", "")  # "Over" or "Under"
                    price = outcome.get("price", 0)  # American odds
                    point = outcome.get("point")  # The line value

                    # Initialize player if not exists
                    if player_name not in markets_dict[market_key]["players"]:
                        markets_dict[market_key]["players"][player_name] = {
                            "player_name": player_name,
                            "line": point,
                            "over": None,
                            "under": None,
                        }

                    # Add over/under odds
                    if over_under == "Over":
                        markets_dict[market_key]["players"][player_name]["over"] = price
                    elif over_under == "Under":
                        markets_dict[market_key]["players"][player_name][
                            "under"
                        ] = price

        # Convert players dict to list
        for market_key in markets_dict:
            markets_dict[market_key]["players"] = list(
                markets_dict[market_key]["players"].values()
            )

        return markets_dict

    async def get_available_markets_for_sport(self, sport: str) -> List[str]:
        """
        Get list of available player prop markets for a sport

        Args:
            sport: Sport key

        Returns:
            List of market keys available for the sport
        """
        return PLAYER_PROP_MARKETS.get(sport, [])

    def get_market_display_name(self, market_key: str) -> str:
        """
        Get human-readable display name for a market key

        Args:
            market_key: The market key (e.g., 'player_pass_tds')

        Returns:
            Human-readable market name
        """
        # Simple conversion: replace underscores with spaces and title case
        # Remove 'player_' prefix
        name = market_key.replace("player_", "").replace("_", " ").title()

        # Special cases
        replacements = {
            "Tds": "Touchdowns",
            "Yds": "Yards",
            "Rbis": "RBIs",
            "Nhl": "NHL",
            "Nba": "NBA",
            "Nfl": "NFL",
            "Mlb": "MLB",
        }

        for old, new in replacements.items():
            name = name.replace(old, new)

        return name
