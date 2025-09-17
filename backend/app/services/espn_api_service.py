"""
ESPN API Service for fetching broadcast and popularity data.

This service handles interactions with ESPN's unofficial API to determine:
- Game broadcast information (national vs local coverage)
- Network data for popularity scoring
- Prime time game identification
"""

import aiohttp
import asyncio
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ESPNSport(str, Enum):
    """ESPN sport keys mapping to their API endpoints"""

    NFL = "nfl"
    NBA = "nba"
    MLB = "mlb"
    NHL = "nhl"
    COLLEGE_FOOTBALL = "college-football"
    COLLEGE_BASKETBALL = "mens-college-basketball"


@dataclass
class BroadcastInfo:
    """Broadcast information for a game"""

    network: Optional[str] = None
    is_national: bool = False
    is_prime_time: bool = False
    popularity_score: int = 0


@dataclass
class PopularGame:
    """Game identified as popular based on broadcast data"""

    id: str
    home_team: str
    away_team: str
    start_time: datetime
    sport: str
    broadcast: BroadcastInfo
    popularity_score: int


class ESPNAPIService:
    """Service for fetching ESPN broadcast data to identify popular games"""

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"

    # National networks that indicate popular games
    NATIONAL_NETWORKS = {
        "ESPN",
        "TNT",
        "ABC",
        "NBC",
        "FOX",
        "CBS",
        "ESPN2",
        "ESPNU",
        "FS1",
        "NBCSN",
        "TBS",
        "Amazon Prime",
        "Apple TV+",
        "Peacock",
        "Prime Video",
        "Apple TV",
        "Netflix",
    }

    # Regional/local networks (lower popularity)
    REGIONAL_NETWORKS = {
        "Bally Sports",
        "YES",
        "NESN",
        "SNY",
        "MSG",
        "Fox Sports Regional",
        "NBC Sports Regional",
    }

    def __init__(self, cache_service=None):
        self.cache_service = cache_service
        self.last_request_time = 0
        self.rate_limit_delay = 1.0  # 1 second between requests

    async def _make_request(self, url: str) -> Optional[Dict]:
        """Make rate-limited request to ESPN API"""
        try:
            # Rate limiting
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.rate_limit_delay:
                await asyncio.sleep(self.rate_limit_delay - time_since_last)

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    self.last_request_time = time.time()

                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.warning(
                            f"ESPN API returned status {response.status} for {url}"
                        )
                        return None

        except Exception as e:
            logger.error(f"Error fetching from ESPN API: {e}")
            return None

    def _calculate_popularity_score(
        self, broadcast_info: BroadcastInfo, game_time: datetime
    ) -> int:
        """Calculate popularity score based on broadcast data and timing"""
        score = 0

        # National network bonus
        if broadcast_info.is_national:
            score += 50

        # Specific network bonuses
        if broadcast_info.network:
            network = broadcast_info.network.upper()
            if "ESPN" in network:
                score += 30
            elif network in ["NBC", "CBS", "FOX", "ABC"]:
                score += 40
            elif network in ["TNT", "TBS"]:
                score += 25
            elif "PRIME" in network or "AMAZON" in network:
                score += 35
            elif "APPLE" in network:
                score += 30

        # Prime time bonus (7-11 PM ET)
        if broadcast_info.is_prime_time:
            score += 30

        # Weekend bonus for afternoon games
        if game_time.weekday() in [5, 6]:  # Saturday, Sunday
            hour = game_time.hour
            if 12 <= hour <= 18:  # Afternoon games
                score += 20

        return score

    def _parse_broadcast_info(self, game_data: Dict) -> BroadcastInfo:
        """Parse broadcast information from ESPN game data"""
        broadcast_info = BroadcastInfo()

        try:
            # Look for broadcast/media information
            competitions = game_data.get("competitions", [])
            if not competitions:
                return broadcast_info

            competition = competitions[0]
            broadcasts = competition.get("broadcasts", [])

            if broadcasts:
                # Get the first (primary) broadcast
                broadcast = broadcasts[0]
                media = broadcast.get("media", {})

                # Extract network name
                network_name = media.get("shortName") or media.get("name")
                if network_name:
                    broadcast_info.network = network_name

                    # Check if it's a national network
                    network_upper = network_name.upper()
                    broadcast_info.is_national = any(
                        nat_net in network_upper for nat_net in self.NATIONAL_NETWORKS
                    )

            # Check for prime time (7-11 PM ET)
            date_str = game_data.get("date")
            if date_str:
                game_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                # Convert to ET for prime time check
                et_hour = (game_time.hour - 5) % 24  # Rough ET conversion
                broadcast_info.is_prime_time = 19 <= et_hour <= 23

        except Exception as e:
            logger.error(f"Error parsing broadcast info: {e}")

        return broadcast_info

    async def get_popular_games_for_sport(
        self, sport: ESPNSport, date: Optional[str] = None
    ) -> List[PopularGame]:
        """Get popular games for a specific sport based on broadcast data"""
        try:
            # Use today if no date specified
            if not date:
                date = datetime.now().strftime("%Y%m%d")

            # Build ESPN API URL
            url = f"{self.BASE_URL}/{sport}/scoreboard"
            if date:
                url += f"?dates={date}"

            # Check cache first
            cache_key = f"espn_popular_{sport}_{date}"
            if self.cache_service:
                cached = await self.cache_service.get(cache_key)
                if cached:
                    return cached

            # Fetch from ESPN API
            data = await self._make_request(url)
            if not data:
                return []

            popular_games = []
            events = data.get("events", [])

            for event in events:
                try:
                    # Parse basic game info
                    game_id = event.get("id")
                    name = event.get("name", "")
                    date_str = event.get("date")

                    if not all([game_id, name, date_str]):
                        continue

                    # Parse teams from name (e.g., "Team A vs Team B")
                    teams = name.split(" vs ")
                    if len(teams) != 2:
                        # Try alternative format
                        teams = name.split(" @ ")

                    if len(teams) != 2:
                        continue

                    away_team, home_team = teams[0].strip(), teams[1].strip()

                    # Parse game time
                    game_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

                    # Parse broadcast information
                    broadcast_info = self._parse_broadcast_info(event)

                    # Calculate popularity score
                    popularity_score = self._calculate_popularity_score(
                        broadcast_info, game_time
                    )
                    broadcast_info.popularity_score = popularity_score

                    # Only include games with significant popularity (national coverage)
                    if popularity_score >= 25:  # Threshold for "popular"
                        popular_game = PopularGame(
                            id=game_id,
                            home_team=home_team,
                            away_team=away_team,
                            start_time=game_time,
                            sport=sport,
                            broadcast=broadcast_info,
                            popularity_score=popularity_score,
                        )
                        popular_games.append(popular_game)

                except Exception as e:
                    logger.error(
                        f"Error processing game {event.get('id', 'unknown')}: {e}"
                    )
                    continue

            # Sort by popularity score
            popular_games.sort(key=lambda x: x.popularity_score, reverse=True)

            # Cache the results for 30 minutes
            if self.cache_service:
                await self.cache_service.set(cache_key, popular_games, expire=1800)

            logger.info(f"Found {len(popular_games)} popular games for {sport}")
            return popular_games

        except Exception as e:
            logger.error(f"Error fetching popular games for {sport}: {e}")
            return []

    async def get_all_popular_games(
        self, date: Optional[str] = None
    ) -> Dict[str, List[PopularGame]]:
        """Get popular games across all supported sports"""
        sports = [ESPNSport.NFL, ESPNSport.NBA, ESPNSport.MLB, ESPNSport.NHL]

        results = {}
        tasks = []

        for sport in sports:
            task = self.get_popular_games_for_sport(sport, date)
            tasks.append((sport, task))

        # Execute all requests concurrently with some delay between them
        for i, (sport, task) in enumerate(tasks):
            if i > 0:
                await asyncio.sleep(0.5)  # Small delay between sport requests
            try:
                games = await task
                results[sport] = games
            except Exception as e:
                logger.error(f"Error fetching popular games for {sport}: {e}")
                results[sport] = []

        return results


# Global service instance
espn_api_service = ESPNAPIService()
