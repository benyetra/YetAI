"""
Games Sync Service - Fetches and caches games from Odds API and ESPN API.

This service runs on a scheduled interval (every 3 hours) to fetch all games
for all leagues (NFL, MLB, NBA, NHL) and store them in the database with odds
and broadcast information. This eliminates rate limiting issues when serving
popular games and provides a single source of truth for game data.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.models.database_models import Game, GameStatus
from app.services.odds_api_service import OddsAPIService
from app.core.database import get_db

logger = logging.getLogger(__name__)


class GamesSyncService:
    """Service to sync games from external APIs to database"""

    # Sports we track
    SPORTS = ["americanfootball_nfl", "baseball_mlb", "basketball_nba", "icehockey_nhl"]

    # How far ahead to fetch games (in days)
    FETCH_DAYS_AHEAD = 7

    def __init__(self, db: Session):
        self.db = db

    async def sync_all_games(self) -> Dict[str, any]:
        """
        Fetch all games from Odds API and ESPN API, store in database.

        Returns:
            Dict with sync statistics (games_fetched, games_updated, errors, etc.)
        """
        logger.info("Starting games sync...")
        start_time = datetime.now(timezone.utc)

        stats = {
            "started_at": start_time.isoformat(),
            "sports_synced": {},
            "total_games_fetched": 0,
            "total_games_created": 0,
            "total_games_updated": 0,
            "errors": [],
            "completed_at": None,
            "duration_seconds": None,
        }

        try:
            # Fetch games from Odds API for each sport
            async with OddsAPIService(settings.ODDS_API_KEY) as odds_service:
                for sport_key in self.SPORTS:
                    try:
                        sport_stats = await self._sync_sport(odds_service, sport_key)
                        stats["sports_synced"][sport_key] = sport_stats
                        stats["total_games_fetched"] += sport_stats["games_fetched"]
                        stats["total_games_created"] += sport_stats["games_created"]
                        stats["total_games_updated"] += sport_stats["games_updated"]
                    except Exception as e:
                        error_msg = f"Failed to sync {sport_key}: {str(e)}"
                        logger.error(error_msg, exc_info=True)
                        stats["errors"].append(error_msg)

            # Commit all changes
            self.db.commit()

            # Fetch broadcast info from ESPN (separate step to avoid rate limits)
            try:
                await self._update_broadcast_info()
            except Exception as e:
                error_msg = f"Failed to update broadcast info: {str(e)}"
                logger.error(error_msg, exc_info=True)
                stats["errors"].append(error_msg)

        except Exception as e:
            error_msg = f"Games sync failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)
            self.db.rollback()

        end_time = datetime.now(timezone.utc)
        stats["completed_at"] = end_time.isoformat()
        stats["duration_seconds"] = (end_time - start_time).total_seconds()

        logger.info(
            f"Games sync completed: {stats['total_games_fetched']} fetched, "
            f"{stats['total_games_created']} created, "
            f"{stats['total_games_updated']} updated"
        )

        return stats

    async def _sync_sport(
        self, odds_service: OddsAPIService, sport_key: str
    ) -> Dict[str, int]:
        """
        Sync games for a specific sport.

        Args:
            odds_service: OddsAPIService instance
            sport_key: Sport key (e.g., "americanfootball_nfl")

        Returns:
            Dict with sport-specific statistics
        """
        logger.info(f"Syncing {sport_key}...")

        stats = {
            "games_fetched": 0,
            "games_created": 0,
            "games_updated": 0,
            "errors": [],
        }

        try:
            # Fetch games from Odds API
            games = await odds_service.get_odds(sport_key)
            stats["games_fetched"] = len(games)

            for game in games:
                try:
                    # Check if game already exists
                    existing_game = (
                        self.db.query(Game).filter(Game.id == game.id).first()
                    )

                    # Prepare odds data (include all bookmakers)
                    odds_data = []
                    for bookmaker in game.bookmakers:
                        odds_data.append(
                            {
                                "key": bookmaker.key,
                                "title": bookmaker.title,
                                "last_update": bookmaker.last_update.isoformat(),
                                "markets": bookmaker.markets,
                            }
                        )

                    if existing_game:
                        # Update existing game
                        existing_game.home_team = game.home_team
                        existing_game.away_team = game.away_team
                        existing_game.commence_time = game.commence_time
                        existing_game.odds_data = odds_data
                        existing_game.last_update = datetime.now(timezone.utc)
                        stats["games_updated"] += 1
                    else:
                        # Create new game
                        new_game = Game(
                            id=game.id,
                            sport_key=game.sport_key,
                            sport_title=game.sport_title,
                            home_team=game.home_team,
                            away_team=game.away_team,
                            commence_time=game.commence_time,
                            status=GameStatus.SCHEDULED,
                            odds_data=odds_data,
                            last_update=datetime.now(timezone.utc),
                        )
                        self.db.add(new_game)
                        stats["games_created"] += 1

                except Exception as e:
                    error_msg = f"Failed to sync game {game.id}: {str(e)}"
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)
                    continue

        except Exception as e:
            error_msg = f"Failed to fetch games for {sport_key}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)

        return stats

    async def _update_broadcast_info(self):
        """
        Update broadcast info from ESPN API for games in the next 7 days.

        This queries ESPN's API to identify nationally televised games and
        adds broadcast network information.
        """
        logger.info("Updating broadcast info from ESPN...")

        # Get games in the next 7 days that don't have broadcast info yet
        eastern = ZoneInfo("America/New_York")
        now = datetime.now(eastern)
        end_date = now + timedelta(days=self.FETCH_DAYS_AHEAD)

        games = (
            self.db.query(Game)
            .filter(
                Game.commence_time >= now.astimezone(timezone.utc),
                Game.commence_time <= end_date.astimezone(timezone.utc),
            )
            .all()
        )

        logger.info(f"Found {len(games)} games to check for broadcast info")

        # ESPN API integration will be added here
        # For now, we'll mark games as nationally televised based on simple heuristics
        # TODO: Integrate with ESPN API to get real broadcast data

        for game in games:
            # Placeholder logic - will be replaced with ESPN API calls
            # Mark prime time NFL games as nationally televised
            if game.sport_key == "americanfootball_nfl":
                game_time_et = game.commence_time.astimezone(eastern)
                hour = game_time_et.hour

                # Thursday Night Football (typically 8:15 PM ET)
                is_tnf = game_time_et.weekday() == 3 and 20 <= hour <= 21

                # Sunday Night Football (typically 8:20 PM ET)
                is_snf = game_time_et.weekday() == 6 and 20 <= hour <= 21

                # Monday Night Football (typically 8:15 PM ET)
                is_mnf = game_time_et.weekday() == 0 and 20 <= hour <= 21

                if is_tnf or is_snf or is_mnf:
                    game.is_nationally_televised = True
                    game.broadcast_info = {
                        "network": (
                            "NBC" if is_snf else "ESPN" if is_mnf else "Prime Video"
                        ),
                        "is_national": True,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }

            # Mark MLB playoff games as nationally televised
            elif game.sport_key == "baseball_mlb":
                # During October (playoff season), mark games as national
                if game.commence_time.month == 10:
                    game.is_nationally_televised = True
                    game.broadcast_info = {
                        "network": "TBS/FOX/ESPN",
                        "is_national": True,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }

            # Mark NBA nationally televised games (placeholder)
            elif game.sport_key == "basketball_nba":
                game_time_et = game.commence_time.astimezone(eastern)
                # Assume games starting 7-10 PM ET might be national
                if 19 <= game_time_et.hour <= 22:
                    game.is_nationally_televised = True
                    game.broadcast_info = {
                        "network": "ESPN/TNT/ABC",
                        "is_national": True,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }

            # Mark NHL nationally televised games
            elif game.sport_key == "icehockey_nhl":
                game_time_et = game.commence_time.astimezone(eastern)
                # NHL games on ESPN/TNT are typically 7-10 PM ET
                if 19 <= game_time_et.hour <= 22:
                    game.is_nationally_televised = True
                    game.broadcast_info = {
                        "network": "ESPN/TNT/ESPN+",
                        "is_national": True,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }

        self.db.commit()
        logger.info("Broadcast info update completed")


async def run_games_sync():
    """
    Entry point for scheduled games sync.

    This function is called by the scheduler service.
    """
    logger.info("Games sync task triggered")

    # Get database session
    db = next(get_db())

    try:
        service = GamesSyncService(db)
        stats = await service.sync_all_games()

        logger.info(f"Games sync completed successfully: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Games sync failed: {str(e)}", exc_info=True)
        raise
    finally:
        db.close()
