"""
ESPN API Service - Fetches broadcast information from ESPN's public API.

This service fetches game schedules with broadcast network information
from ESPN's unofficial/hidden API endpoints.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


class ESPNAPIService:
    """Service to fetch broadcast information from ESPN API"""

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"

    # Sport mappings
    SPORT_ENDPOINTS = {
        "americanfootball_nfl": "football/nfl",
        "basketball_nba": "basketball/nba",
        "baseball_mlb": "baseball/mlb",
        "icehockey_nhl": "hockey/nhl",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; YetAI-Sports/1.0)",
            }
        )

    def get_scoreboard(self, sport_key: str) -> Optional[Dict]:
        """
        Fetch scoreboard data from ESPN API for a specific sport.

        Args:
            sport_key: Sport key (e.g., 'americanfootball_nfl')

        Returns:
            Dict with ESPN scoreboard data or None if error
        """
        endpoint = self.SPORT_ENDPOINTS.get(sport_key)
        if not endpoint:
            logger.warning(f"No ESPN endpoint mapping for sport: {sport_key}")
            return None

        url = f"{self.BASE_URL}/{endpoint}/scoreboard"

        try:
            logger.info(f"Fetching ESPN scoreboard for {sport_key}: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            logger.info(
                f"Successfully fetched ESPN data for {sport_key}: {len(data.get('events', []))} events"
            )
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching ESPN scoreboard for {sport_key}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching ESPN data: {e}")
            return None

    def extract_broadcast_info(
        self, home_team: str, away_team: str, commence_time: datetime, sport_key: str
    ) -> Optional[Dict]:
        """
        Extract broadcast information for a specific game.

        Args:
            home_team: Home team name
            away_team: Away team name
            commence_time: Game start time
            sport_key: Sport key

        Returns:
            Dict with broadcast info or None
        """
        scoreboard = self.get_scoreboard(sport_key)
        if not scoreboard or "events" not in scoreboard:
            return None

        # Try to find matching game
        for event in scoreboard.get("events", []):
            # Check if game time matches (within 1 hour tolerance)
            try:
                event_time = datetime.fromisoformat(
                    event.get("date", "").replace("Z", "+00:00")
                )
                time_diff = abs((event_time - commence_time).total_seconds())
                if time_diff > 3600:  # More than 1 hour difference
                    continue
            except (ValueError, AttributeError):
                continue

            # Check if teams match
            competitions = event.get("competitions", [])
            if not competitions:
                continue

            competition = competitions[0]
            competitors = competition.get("competitors", [])

            # Extract team names from competitors
            espn_home = None
            espn_away = None
            for competitor in competitors:
                team = competitor.get("team", {})
                team_name = f"{team.get('location', '')} {team.get('name', '')}".strip()

                if competitor.get("homeAway") == "home":
                    espn_home = team_name
                elif competitor.get("homeAway") == "away":
                    espn_away = team_name

            # Check if teams match (case-insensitive)
            if espn_home and espn_away:
                if (
                    home_team.lower() in espn_home.lower()
                    or espn_home.lower() in home_team.lower()
                ) and (
                    away_team.lower() in espn_away.lower()
                    or espn_away.lower() in away_team.lower()
                ):
                    # Extract broadcast information
                    return self._parse_broadcast_info(event, competition)

        logger.debug(
            f"No ESPN broadcast match found for {away_team} @ {home_team} at {commence_time}"
        )
        return None

    def _parse_broadcast_info(
        self, event: Dict, competition: Dict = None
    ) -> Optional[Dict]:
        """
        Parse broadcast information from ESPN event data.

        Args:
            event: ESPN event dict
            competition: ESPN competition dict (optional, contains broadcast data)

        Returns:
            Broadcast info dict with network, is_national, etc.
        """
        broadcast_info = {
            "networks": [],
            "is_national": False,
            "streaming": [],
        }

        # Check competition-level broadcasts first (most reliable source)
        if competition:
            comp_broadcasts = competition.get("broadcasts", [])
            for broadcast in comp_broadcasts:
                market = broadcast.get("market", "")
                names = broadcast.get("names", [])

                if market == "national":
                    broadcast_info["is_national"] = True

                for name in names:
                    if name and name not in broadcast_info["networks"]:
                        broadcast_info["networks"].append(name)

            # Check competition-level geoBroadcasts
            comp_geo_broadcasts = competition.get("geoBroadcasts", [])
            for geo_broadcast in comp_geo_broadcasts:
                media = geo_broadcast.get("media", {})
                network = media.get("shortName", "")
                market = geo_broadcast.get("market", {})
                broadcast_type = geo_broadcast.get("type", {}).get("shortName", "")

                # Only add TV networks, skip Radio
                if network and broadcast_type != "Radio":
                    if network not in broadcast_info["networks"]:
                        broadcast_info["networks"].append(network)

                    # Track streaming services separately
                    if broadcast_type == "Streaming":
                        if network not in broadcast_info["streaming"]:
                            broadcast_info["streaming"].append(network)

                if market.get("type") == "National":
                    broadcast_info["is_national"] = True

        # Also check event-level broadcasts (fallback)
        broadcasts = event.get("broadcasts", [])
        for broadcast in broadcasts:
            market = broadcast.get("market", "")
            names = broadcast.get("names", [])

            if market == "national":
                broadcast_info["is_national"] = True

            for name in names:
                if name and name not in broadcast_info["networks"]:
                    broadcast_info["networks"].append(name)

        # Check event-level geoBroadcasts
        geo_broadcasts = event.get("geoBroadcasts", [])
        for geo_broadcast in geo_broadcasts:
            media = geo_broadcast.get("media", {})
            network = media.get("shortName", "")
            market = geo_broadcast.get("market", {})
            broadcast_type = geo_broadcast.get("type", {}).get("shortName", "")

            # Only add TV networks, skip Radio
            if network and broadcast_type != "Radio":
                if network not in broadcast_info["networks"]:
                    broadcast_info["networks"].append(network)

                # Track streaming services separately
                if broadcast_type == "Streaming":
                    if network not in broadcast_info["streaming"]:
                        broadcast_info["streaming"].append(network)

            if market.get("type") == "National":
                broadcast_info["is_national"] = True

        # If no networks found, return None
        if not broadcast_info["networks"]:
            return None

        return broadcast_info


# Global instance
espn_api_service = ESPNAPIService()
