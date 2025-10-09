"""
Optimized OddsAPI Service with efficient rate limit management

Key optimizations:
1. Use events endpoint (FREE) for game discovery
2. Single bookmaker (FanDuel) to reduce costs
3. Smart batching and caching to minimize API calls
4. Proper usage tracking with response headers
5. Efficient scores fetching with daysFrom parameter
"""

import aiohttp
import asyncio
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone
import logging
from dataclasses import dataclass
from enum import Enum
from app.services.odds_api_service import SportKey, MarketKey

logger = logging.getLogger(__name__)


@dataclass
class UsageStats:
    """Track API usage statistics"""

    requests_used: int = 0
    requests_remaining: int = 0
    last_request_cost: int = 0
    daily_requests: int = 0
    monthly_requests: int = 0
    last_updated: datetime = datetime.utcnow()


class OptimizedOddsAPIService:
    """
    Optimized Odds API service that minimizes usage costs

    Cost optimization strategies:
    - Events endpoint: FREE (use for game discovery)
    - Scores with daysFrom=3: 2 credits (get completed games)
    - Scores without daysFrom: 1 credit (live games only)
    - Single bookmaker (FanDuel): Reduces costs dramatically
    - Smart caching to avoid duplicate requests
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.the-odds-api.com/v4"
        self.usage_stats = UsageStats()
        self.session = None

        # Optimize for single bookmaker to reduce costs
        self.bookmaker = "fanduel"  # Single trusted bookmaker
        self.region = "us"

        # Cache to avoid duplicate requests
        self.cache = {}
        self.cache_duration = 300  # 5 minutes for events, shorter for scores

    async def _ensure_session(self):
        """Ensure aiohttp session exists"""
        if self.session is None:
            self.session = aiohttp.ClientSession()

    async def _make_request(
        self, endpoint: str, params: Dict[str, Any]
    ) -> Tuple[Any, Dict[str, str]]:
        """
        Make API request and track usage

        Returns:
            Tuple of (response_data, headers)
        """
        await self._ensure_session()

        # Add API key
        params["apiKey"] = self.api_key

        url = f"{self.base_url}{endpoint}"

        logger.info(f"Making optimized API request to {endpoint}")

        async with self.session.get(url, params=params) as response:
            headers = dict(response.headers)

            # Update usage stats from response headers
            self._update_usage_stats(headers)

            if response.status == 429:
                logger.error("Rate limit exceeded - requests too frequent")
                raise Exception("Rate limit exceeded")
            elif response.status == 401:
                logger.error("Out of usage credits")
                raise Exception("OUT_OF_USAGE_CREDITS")

            response.raise_for_status()
            data = await response.json()

            return data, headers

    def _update_usage_stats(self, headers: Dict[str, str]):
        """Update usage statistics from response headers"""
        try:
            self.usage_stats.requests_remaining = int(
                headers.get("x-requests-remaining", 0)
            )
            self.usage_stats.requests_used = int(headers.get("x-requests-used", 0))
            self.usage_stats.last_request_cost = int(headers.get("x-requests-last", 0))
            self.usage_stats.last_updated = datetime.utcnow()

            logger.info(
                f"API Usage: {self.usage_stats.requests_used} used, "
                f"{self.usage_stats.requests_remaining} remaining, "
                f"last cost: {self.usage_stats.last_request_cost}"
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not parse usage headers: {e}")

    async def get_events(self, sport: str) -> List[Dict[str, Any]]:
        """
        Get events for a sport (FREE endpoint)

        This endpoint costs 0 credits and returns basic game info
        Use this for game discovery and scheduling
        """
        cache_key = f"events_{sport}"

        # Check cache first
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if time.time() - cached_time < self.cache_duration:
                logger.info(f"Using cached events for {sport}")
                return cached_data

        endpoint = f"/sports/{sport}/events"
        params = {"dateFormat": "iso"}

        data, headers = await self._make_request(endpoint, params)

        # Cache the result
        self.cache[cache_key] = (data, time.time())

        logger.info(f"Retrieved {len(data)} events for {sport} (FREE)")
        return data

    async def get_scores_optimized(
        self, sport: str, include_completed: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get scores with optimized usage

        Args:
            sport: Sport key
            include_completed: If True, gets completed games (costs 2), otherwise live only (costs 1)
        """
        cache_key = f"scores_{sport}_{include_completed}"
        cache_duration = (
            60 if include_completed else 30
        )  # Shorter cache for live scores

        # Check cache
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if time.time() - cached_time < cache_duration:
                logger.info(f"Using cached scores for {sport}")
                return cached_data

        endpoint = f"/sports/{sport}/scores"
        params = {"dateFormat": "iso"}

        # Only add daysFrom if we need completed games (costs 2 instead of 1)
        if include_completed:
            params["daysFrom"] = "3"  # Get games completed in last 3 days
            expected_cost = 2
        else:
            expected_cost = 1

        logger.info(f"Fetching scores for {sport}, expected cost: {expected_cost}")

        data, headers = await self._make_request(endpoint, params)

        # Cache the result
        self.cache[cache_key] = (data, time.time())

        completed_games = [g for g in data if g.get("completed", False)]
        live_games = [g for g in data if not g.get("completed", False)]

        logger.info(
            f"Retrieved {len(data)} games for {sport}: "
            f"{len(completed_games)} completed, {len(live_games)} live/upcoming"
        )

        return data

    async def get_odds_single_bookmaker(
        self, sport: str, event_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get odds for specific games using single bookmaker to minimize costs

        Cost: markets × regions = 3 × 1 = 3 credits per request
        """
        endpoint = f"/sports/{sport}/odds"
        params = {
            "regions": self.region,
            "bookmakers": self.bookmaker,  # Single bookmaker
            "markets": "h2h,spreads,totals",  # Core markets only
            "dateFormat": "iso",
            "oddsFormat": "american",
        }

        if event_ids:
            params["eventIds"] = ",".join(event_ids)

        expected_cost = 3  # 3 markets × 1 region
        logger.info(f"Fetching odds for {sport}, expected cost: {expected_cost}")

        data, headers = await self._make_request(endpoint, params)

        logger.info(f"Retrieved odds for {len(data)} games from {self.bookmaker}")
        return data

    async def verify_bets_efficiently(
        self, game_ids_by_sport: Dict[str, List[str]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Efficiently verify bets by minimizing API calls

        Strategy:
        1. Use events endpoint (FREE) to get basic game info
        2. Use scores with daysFrom=3 (cost: 2) to get completed games
        3. Batch requests by sport to minimize calls
        """
        results = {}

        for sport, game_ids in game_ids_by_sport.items():
            logger.info(f"Verifying {len(game_ids)} games for {sport}")

            # Step 1: Get completed games (costs 2 credits)
            completed_games = await self.get_scores_optimized(
                sport, include_completed=True
            )

            # Filter to only the games we care about
            relevant_games = []
            for game in completed_games:
                if game.get("id") in game_ids and game.get("completed", False):
                    relevant_games.append(game)

            results[sport] = relevant_games

            logger.info(f"Found {len(relevant_games)} completed games for {sport}")

        return results

    def get_usage_summary(self) -> Dict[str, Any]:
        """Get current usage summary"""
        return {
            "requests_used": self.usage_stats.requests_used,
            "requests_remaining": self.usage_stats.requests_remaining,
            "last_request_cost": self.usage_stats.last_request_cost,
            "last_updated": self.usage_stats.last_updated.isoformat(),
            "optimization_enabled": True,
            "bookmaker": self.bookmaker,
            "strategy": "single_bookmaker_with_caching",
        }

    async def close(self):
        """Close aiohttp session"""
        if self.session:
            await self.session.close()


# Singleton instance
optimized_odds_api_service = None


def get_optimized_odds_service(api_key: str) -> OptimizedOddsAPIService:
    """Get singleton instance of optimized odds service"""
    global optimized_odds_api_service
    if optimized_odds_api_service is None:
        optimized_odds_api_service = OptimizedOddsAPIService(api_key)
    return optimized_odds_api_service
