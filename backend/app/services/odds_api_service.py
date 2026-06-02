"""
OddsAPI Service for fetching live sports data from The Odds API v4.

This service handles all interactions with The Odds API including:
- Sports list retrieval
- Live odds fetching
- Game scores and results
- Rate limiting and error handling
"""

import aiohttp
import asyncio
import contextvars
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

_odds_api_caller: contextvars.ContextVar[str] = contextvars.ContextVar(
    "odds_api_caller", default="unknown"
)


@contextmanager
def odds_api_call_scope(caller: str):
    """Tag downstream Odds API requests with a logical caller name."""
    token = _odds_api_caller.set(caller)
    try:
        yield
    finally:
        _odds_api_caller.reset(token)


class SportKey(str, Enum):
    """Supported sport keys from The Odds API"""

    AMERICANFOOTBALL_NFL = "americanfootball_nfl"
    AMERICANFOOTBALL_NCAAF = "americanfootball_ncaaf"
    BASKETBALL_NBA = "basketball_nba"
    BASKETBALL_NCAAB = "basketball_ncaab"
    BASKETBALL_WNBA = "basketball_wnba"
    BASEBALL_MLB = "baseball_mlb"
    ICEHOCKEY_NHL = "icehockey_nhl"
    SOCCER_EPL = "soccer_epl"
    SOCCER_MLS = "soccer_mls"
    SOCCER_UEFA_CHAMPS_LEAGUE = "soccer_uefa_champs_league"
    SOCCER_FIFA_WORLD_CUP = "soccer_fifa_world_cup"
    GOLF_PGA = "golf_pga"
    TENNIS_ATP = "tennis_atp"
    TENNIS_WTA = "tennis_wta"
    MMA_MIXED_MARTIAL_ARTS = "mma_mixed_martial_arts"
    BOXING_HEAVYWEIGHT = "boxing_heavyweight"


class MarketKey(str, Enum):
    """Available betting markets"""

    H2H = "h2h"  # Head to head (moneyline)
    SPREADS = "spreads"  # Point spreads
    TOTALS = "totals"  # Over/under totals


class OddsFormat(str, Enum):
    """Odds format options"""

    DECIMAL = "decimal"
    AMERICAN = "american"


# Rough in-season month windows (UTC) per sport. Used to skip Odds API calls for
# sports that are clearly out of season. Unknown sports default to in-season.
_SPORT_SEASON_MONTHS = {
    "americanfootball_nfl": {9, 10, 11, 12, 1, 2},
    "americanfootball_ncaaf": {8, 9, 10, 11, 12, 1},
    "basketball_nba": {10, 11, 12, 1, 2, 3, 4, 5, 6},
    "basketball_wnba": {5, 6, 7, 8, 9, 10},
    "baseball_mlb": {3, 4, 5, 6, 7, 8, 9, 10},
    "icehockey_nhl": {10, 11, 12, 1, 2, 3, 4, 5, 6},
    "soccer_epl": {8, 9, 10, 11, 12, 1, 2, 3, 4, 5},
    "soccer_mls": {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12},
}


def sport_in_season(sport_key: str, *, month: Optional[int] = None) -> bool:
    """Return True when ``sport_key`` is plausibly in season this month."""
    months = _SPORT_SEASON_MONTHS.get(sport_key)
    if not months:
        return True
    current_month = month if month is not None else datetime.utcnow().month
    return current_month in months


@dataclass
class Bookmaker:
    """Represents a bookmaker and their odds"""

    key: str
    title: str
    last_update: datetime
    markets: List[Dict[str, Any]]


@dataclass
class Game:
    """Represents a game/match with odds"""

    id: str
    sport_key: str
    sport_title: str
    commence_time: datetime
    home_team: str
    away_team: str
    bookmakers: List[Bookmaker]


@dataclass
class Score:
    """Represents a completed game score"""

    id: str
    sport_key: str
    sport_title: str
    commence_time: datetime
    home_team: str
    away_team: str
    completed: bool
    home_score: Optional[int]
    away_score: Optional[int]
    last_update: datetime


class OddsAPIService:
    """Service for interacting with The Odds API v4"""

    BASE_URL = "https://api.the-odds-api.com/v4"

    # Rate limiting constants
    MONTHLY_LIMIT = 20000  # Maximum requests per month
    DAILY_LIMIT = (
        700  # Conservative daily limit (20000/30 = 666, rounded up for safety)
    )

    def __init__(self, api_key: str):
        """
        Initialize the service with API key

        Args:
            api_key: Your Odds API key
        """
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limit_remaining = 500  # Default quota
        self.rate_limit_used = 0
        self.last_request_time = 0

        # Track daily/monthly usage
        self.daily_requests = 0
        self.monthly_requests = 0
        self.last_reset_date = datetime.utcnow().date()
        self.current_month = datetime.utcnow().month

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    def _reset_counters_if_needed(self) -> None:
        """Reset daily/monthly counters if needed"""
        now = datetime.utcnow()
        current_date = now.date()
        current_month = now.month

        # Reset daily counter if it's a new day
        if current_date != self.last_reset_date:
            logger.info(f"Resetting daily request counter (was {self.daily_requests})")
            self.daily_requests = 0
            self.last_reset_date = current_date

        # Reset monthly counter if it's a new month
        if current_month != self.current_month:
            logger.info(
                f"Resetting monthly request counter (was {self.monthly_requests})"
            )
            self.monthly_requests = 0
            self.current_month = current_month

    def _get_team_score(self, scores: List[Dict], team_name: str) -> Optional[int]:
        """
        Get the score for a specific team from the scores array.

        Args:
            scores: List of score objects from API
            team_name: Name of the team to find score for

        Returns:
            Score for the team or None if not found
        """
        if not scores:
            return None

        for score_obj in scores:
            if score_obj.get("name") == team_name:
                return score_obj.get("score")

        # Fallback: if we can't match by name, use the old logic but log a warning
        logger.warning(
            f"Could not match team '{team_name}' in scores array, using fallback logic"
        )

        # For Cardinals vs Reds case - if we have exactly 2 scores
        if len(scores) >= 2:
            # Log the available teams for debugging
            team_names = [score.get("name", "Unknown") for score in scores]
            logger.warning(f"Available teams in scores: {team_names}")

            # Try to match by partial name comparison
            for i, score_obj in enumerate(scores):
                score_team_name = score_obj.get("name", "").lower()
                target_team_name = team_name.lower()

                # Check if team names have any overlap (e.g., "Cardinals" in "St. Louis Cardinals")
                if any(
                    word in score_team_name for word in target_team_name.split()
                ) or any(word in target_team_name for word in score_team_name.split()):
                    logger.info(
                        f"Matched '{team_name}' with '{score_obj.get('name')}' by partial name"
                    )
                    return score_obj.get("score")

        logger.error(
            f"Failed to find score for team '{team_name}' in {len(scores)} score entries"
        )
        return None

    def _check_rate_limit(self) -> bool:
        """
        Check if we're within rate limits

        Returns:
            True if we can make a request, False if we should wait
        """
        self._reset_counters_if_needed()

        # Check API provider rate limit
        if self.rate_limit_remaining <= 0:
            logger.warning("API provider rate limit exceeded")
            return False

        # Check our daily limit
        if self.daily_requests >= self.DAILY_LIMIT:
            logger.warning(
                f"Daily request limit exceeded ({self.daily_requests}/{self.DAILY_LIMIT})"
            )
            return False

        # Check our monthly limit
        if self.monthly_requests >= self.MONTHLY_LIMIT:
            logger.warning(
                f"Monthly request limit exceeded ({self.monthly_requests}/{self.MONTHLY_LIMIT})"
            )
            return False

        return True

    def _update_rate_limit(self, headers: Dict[str, str]) -> None:
        """
        Update rate limit counters from response headers

        Args:
            headers: Response headers from The Odds API
        """
        try:
            self.rate_limit_remaining = int(headers.get("x-requests-remaining", 0))
            self.rate_limit_used = int(headers.get("x-requests-used", 0))

            # Increment our tracking counters
            self.daily_requests += 1
            self.monthly_requests += 1

            last_cost = headers.get("x-requests-last", "?")
            logger.info(
                "Odds API call caller=%s remaining=%s used=%s last_cost=%s",
                _odds_api_caller.get(),
                self.rate_limit_remaining,
                self.rate_limit_used,
                last_cost,
            )
            logger.debug(
                "Odds API process counters: %s/%s daily, %s/%s monthly",
                self.daily_requests,
                self.DAILY_LIMIT,
                self.monthly_requests,
                self.MONTHLY_LIMIT,
            )
        except (ValueError, TypeError):
            logger.warning("Could not parse rate limit headers")

    async def _make_request(
        self, endpoint: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Make a request to The Odds API

        Args:
            endpoint: API endpoint (without base URL)
            params: Query parameters

        Returns:
            JSON response data

        Raises:
            Exception: If request fails or rate limit exceeded
        """
        if not self._check_rate_limit():
            raise Exception("Rate limit exceeded")

        if not self.session:
            raise Exception("Session not initialized. Use async context manager.")

        url = f"{self.BASE_URL}{endpoint}"
        request_params = {"apiKey": self.api_key}
        if params:
            request_params.update(params)

        try:
            self.last_request_time = time.time()
            async with self.session.get(url, params=request_params) as response:
                self._update_rate_limit(dict(response.headers))

                if response.status == 401:
                    raise Exception("Invalid API key")
                elif response.status == 422:
                    error_text = await response.text()
                    raise Exception(f"Invalid request parameters: {error_text}")
                elif response.status == 429:
                    raise Exception("Rate limit exceeded")
                elif response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"API request failed with status {response.status}: {error_text}"
                    )

                return await response.json()

        except aiohttp.ClientError as e:
            logger.error(f"Network error making request to {url}: {e}")
            raise Exception(f"Network error: {e}")

    async def get_sports(self) -> List[Dict[str, Any]]:
        """
        Get list of available sports

        Returns:
            List of sport dictionaries with keys: key, group, title, description, active, has_outrights
        """
        try:
            data = await self._make_request("/sports")
            logger.info(f"Retrieved {len(data)} sports")
            return data
        except Exception as e:
            logger.error(f"Failed to get sports: {e}")
            raise

    async def get_odds(
        self,
        sport: str,
        regions: str = "us",
        markets: str = "h2h,spreads,totals",
        odds_format: OddsFormat = OddsFormat.AMERICAN,
        date_format: str = "iso",
        bookmakers: Optional[str] = None,
        commence_time_from: Optional[datetime] = None,
        commence_time_to: Optional[datetime] = None,
    ) -> List[Game]:
        """
        Get live odds for a specific sport

        Args:
            sport: Sport key (e.g., 'americanfootball_nfl')
            regions: Comma-separated regions (us, uk, au, eu)
            markets: Comma-separated markets (h2h, spreads, totals)
            odds_format: Format for odds (american, decimal)
            date_format: Date format (iso, unix)
            bookmakers: Comma-separated bookmaker keys
            commence_time_from: Filter games starting after this time
            commence_time_to: Filter games starting before this time

        Returns:
            List of Game objects with odds data
        """
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format.value,
            "dateFormat": date_format,
        }

        if bookmakers:
            params["bookmakers"] = bookmakers
        if commence_time_from:
            params["commenceTimeFrom"] = commence_time_from.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        if commence_time_to:
            params["commenceTimeTo"] = commence_time_to.strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            data = await self._make_request(f"/sports/{sport}/odds", params)

            games = []
            for game_data in data:
                bookmakers_list = []
                for bm_data in game_data.get("bookmakers", []):
                    bookmaker = Bookmaker(
                        key=bm_data["key"],
                        title=bm_data["title"],
                        last_update=datetime.fromisoformat(
                            bm_data["last_update"].replace("Z", "+00:00")
                        ),
                        markets=bm_data.get("markets", []),
                    )
                    bookmakers_list.append(bookmaker)

                game = Game(
                    id=game_data["id"],
                    sport_key=game_data["sport_key"],
                    sport_title=game_data["sport_title"],
                    commence_time=datetime.fromisoformat(
                        game_data["commence_time"].replace("Z", "+00:00")
                    ),
                    home_team=game_data["home_team"],
                    away_team=game_data["away_team"],
                    bookmakers=bookmakers_list,
                )
                games.append(game)

            logger.info(f"Retrieved odds for {len(games)} games in {sport}")
            return games

        except Exception as e:
            logger.error(f"Failed to get odds for {sport}: {e}")
            raise

    async def get_scores(
        self, sport: str, days_from: int = None, date_format: str = "iso"
    ) -> List[Score]:
        """
        Get scores for live and/or completed games

        Args:
            sport: Sport key (e.g., 'americanfootball_nfl')
            days_from: Number of days in the past to return scores from (1-3).
                      If None, only returns live games (costs 1 credit).
                      If specified, returns completed + live games (costs 2 credits).
            date_format: Date format (iso, unix)

        Returns:
            List of Score objects
        """
        params = {"dateFormat": date_format}

        # Only include daysFrom if specified (omitting it gets only live games - cheaper!)
        if days_from is not None:
            params["daysFrom"] = days_from

        try:
            data = await self._make_request(f"/sports/{sport}/scores", params)

            # Handle case where API returns None or empty response
            if not data:
                logger.info(f"No scores data returned for {sport}")
                return []

            scores = []
            for score_data in data:
                score = Score(
                    id=score_data["id"],
                    sport_key=score_data["sport_key"],
                    sport_title=score_data["sport_title"],
                    commence_time=(
                        datetime.fromisoformat(
                            score_data["commence_time"].replace("Z", "+00:00")
                        )
                        if score_data.get("commence_time")
                        else datetime.now()
                    ),
                    home_team=score_data["home_team"],
                    away_team=score_data["away_team"],
                    completed=score_data.get("completed", False),
                    home_score=self._get_team_score(
                        score_data.get("scores", []), score_data["home_team"]
                    ),
                    away_score=self._get_team_score(
                        score_data.get("scores", []), score_data["away_team"]
                    ),
                    last_update=(
                        datetime.fromisoformat(
                            score_data["last_update"].replace("Z", "+00:00")
                        )
                        if score_data.get("last_update")
                        else datetime.now()
                    ),
                )
                scores.append(score)

            logger.info(f"Retrieved {len(scores)} scores for {sport}")
            return scores

        except Exception as e:
            logger.error(f"Failed to get scores for {sport}: {e}")
            raise

    async def get_event_odds(
        self,
        sport: str,
        event_id: str,
        regions: str = "us",
        markets: str = "h2h,spreads,totals",
        odds_format: OddsFormat = OddsFormat.AMERICAN,
        date_format: str = "iso",
        bookmakers: Optional[str] = None,
    ) -> Optional[Game]:
        """
        Get odds for a specific event/game

        Args:
            sport: Sport key
            event_id: Specific event ID
            regions: Comma-separated regions
            markets: Comma-separated markets
            odds_format: Format for odds
            date_format: Date format
            bookmakers: Comma-separated bookmaker keys

        Returns:
            Game object with odds data or None if not found
        """
        params = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format.value,
            "dateFormat": date_format,
        }

        if bookmakers:
            params["bookmakers"] = bookmakers

        try:
            data = await self._make_request(
                f"/sports/{sport}/events/{event_id}/odds", params
            )

            if not data:
                return None

            bookmakers_list = []
            for bm_data in data.get("bookmakers", []):
                # Handle last_update - it may not always be present in the API response
                last_update = datetime.utcnow()  # Default to current time
                if "last_update" in bm_data:
                    try:
                        last_update = datetime.fromisoformat(
                            bm_data["last_update"].replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError) as e:
                        logger.warning(
                            f"Could not parse last_update for bookmaker {bm_data.get('key')}: {e}"
                        )

                bookmaker = Bookmaker(
                    key=bm_data["key"],
                    title=bm_data["title"],
                    last_update=last_update,
                    markets=bm_data.get("markets", []),
                )
                bookmakers_list.append(bookmaker)

            game = Game(
                id=data["id"],
                sport_key=data["sport_key"],
                sport_title=data["sport_title"],
                commence_time=datetime.fromisoformat(
                    data["commence_time"].replace("Z", "+00:00")
                ),
                home_team=data["home_team"],
                away_team=data["away_team"],
                bookmakers=bookmakers_list,
            )

            logger.info(f"Retrieved odds for event {event_id}")
            return game

        except Exception as e:
            logger.error(f"Failed to get odds for event {event_id}: {e}")
            raise

    def get_rate_limit_status(self) -> Dict[str, Any]:
        """
        Get current rate limit status

        Returns:
            Dictionary with rate limit information
        """
        self._reset_counters_if_needed()

        return {
            "api_requests_used": self.rate_limit_used,
            "api_requests_remaining": self.rate_limit_remaining,
            "daily_requests": self.daily_requests,
            "daily_limit": self.DAILY_LIMIT,
            "daily_remaining": max(0, self.DAILY_LIMIT - self.daily_requests),
            "monthly_requests": self.monthly_requests,
            "monthly_limit": self.MONTHLY_LIMIT,
            "monthly_remaining": max(0, self.MONTHLY_LIMIT - self.monthly_requests),
            "last_request_time": self.last_request_time,
            "last_reset_date": self.last_reset_date.isoformat(),
            "current_month": self.current_month,
        }

    def get_usage_stats(self) -> Dict[str, Any]:
        """
        Get detailed usage statistics for monitoring

        Returns:
            Dictionary with comprehensive usage data
        """
        self._reset_counters_if_needed()

        # Calculate usage percentages
        daily_pct = (
            (self.daily_requests / self.DAILY_LIMIT) * 100
            if self.DAILY_LIMIT > 0
            else 0
        )
        monthly_pct = (
            (self.monthly_requests / self.MONTHLY_LIMIT) * 100
            if self.MONTHLY_LIMIT > 0
            else 0
        )

        return {
            "daily": {
                "used": self.daily_requests,
                "limit": self.DAILY_LIMIT,
                "remaining": max(0, self.DAILY_LIMIT - self.daily_requests),
                "percentage_used": round(daily_pct, 2),
            },
            "monthly": {
                "used": self.monthly_requests,
                "limit": self.MONTHLY_LIMIT,
                "remaining": max(0, self.MONTHLY_LIMIT - self.monthly_requests),
                "percentage_used": round(monthly_pct, 2),
            },
            "warnings": {
                "daily_near_limit": daily_pct >= 80,
                "monthly_near_limit": monthly_pct >= 80,
                "daily_exceeded": self.daily_requests >= self.DAILY_LIMIT,
                "monthly_exceeded": self.monthly_requests >= self.MONTHLY_LIMIT,
            },
        }


# Utility functions for common operations


async def get_popular_sports_odds() -> List[Game]:
    """
    Get odds for filtered sports (mlb, nba, nhl, nfl, ncaaf, ncaab, wnba, epl, mls)

    Returns:
        Combined list of games from filtered sports
    """
    from ..core.config import settings

    # Define allowed sports - only these are shown on the site
    allowed_sports = [
        SportKey.AMERICANFOOTBALL_NFL,  # nfl
        SportKey.AMERICANFOOTBALL_NCAAF,  # ncaaf
        SportKey.BASKETBALL_NBA,  # nba
        SportKey.BASKETBALL_NCAAB,  # ncaab
        SportKey.BASKETBALL_WNBA,  # wnba
        SportKey.BASEBALL_MLB,  # mlb
        SportKey.ICEHOCKEY_NHL,  # nhl
        SportKey.SOCCER_EPL,  # epl
        SportKey.SOCCER_MLS,  # mls
    ]

    all_games = []
    successful_sports = []
    failed_sports = []

    async with OddsAPIService(settings.ODDS_API_KEY) as service:
        for i, sport in enumerate(allowed_sports):
            try:
                sport_key = sport.value if hasattr(sport, "value") else sport
                logger.info(f"Fetching odds for {sport_key}")
                games = await service.get_odds(sport_key)
                if games:
                    all_games.extend(games)
                    successful_sports.append(sport_key)
                    logger.info(
                        f"Successfully fetched {len(games)} games for {sport_key}"
                    )
                else:
                    logger.warning(f"No games available for {sport_key}")
            except Exception as e:
                sport_key = sport.value if hasattr(sport, "value") else sport
                failed_sports.append(f"{sport_key}: {str(e)}")
                logger.error(f"Failed to get odds for {sport_key}: {e}")
                continue

            # Add delay between API calls to avoid rate limiting (except after last sport)
            if i < len(allowed_sports) - 1:
                await asyncio.sleep(1.5)  # 1.5 second delay between sports

    logger.info(
        f"Popular odds fetch completed. Success: {successful_sports}, Failed: {failed_sports}"
    )

    # If no games found at all, raise an error
    if not all_games:
        error_msg = (
            f"No games available from any popular sports. Failed: {failed_sports}"
        )
        logger.error(error_msg)
        raise HTTPException(status_code=404, detail=error_msg)

    return all_games
