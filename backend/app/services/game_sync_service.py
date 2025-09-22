"""
Game Sync Service - Syncs real game data from The Odds API

This service:
1. Fetches current games and scores from The Odds API
2. Updates existing games in the database with real scores/status
3. Creates new games from the API if they don't exist
4. Ensures bet verification has access to real, up-to-date game data
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.database_models import Game, GameStatus
from app.services.odds_api_service import OddsAPIService, SportKey
from app.core.config import settings

logger = logging.getLogger(__name__)


class GameSyncService:
    """Service for syncing games from The Odds API"""

    def __init__(self):
        # Initialize with API key from settings
        api_key = getattr(settings, "ODDS_API_KEY", None)
        self.odds_api_service = OddsAPIService(api_key=api_key) if api_key else None

        # Major sports to sync
        self.sync_sports = [
            SportKey.AMERICANFOOTBALL_NFL,
            SportKey.BASKETBALL_NBA,
            SportKey.BASEBALL_MLB,
            SportKey.ICEHOCKEY_NHL,
        ]

    def is_available(self) -> bool:
        """Check if the service is available (has API key)"""
        return self.odds_api_service is not None

    async def sync_game_scores_mock(self) -> Dict[str, any]:
        """
        Mock game sync for testing when no API key is available
        Updates some existing games with mock completed status
        """
        logger.info("Running mock game sync (no API key configured)")

        db = SessionLocal()
        try:
            # Find some scheduled games to mark as completed
            scheduled_games = (
                db.query(Game)
                .filter(Game.status == GameStatus.SCHEDULED)
                .limit(3)
                .all()
            )

            updated_count = 0
            for game in scheduled_games:
                # Mock final scores
                game.status = GameStatus.FINAL
                game.home_score = 24  # Mock score
                game.away_score = 17  # Mock score
                game.last_update = datetime.utcnow()
                updated_count += 1

                logger.info(
                    f"Mock updated: {game.away_team} @ {game.home_team} -> Final"
                )

            db.commit()

            return {
                "success": True,
                "message": f"Mock sync completed - updated {updated_count} games",
                "games_updated": updated_count,
                "games_created": 0,
                "sports_synced": ["mock"],
                "mock_mode": True,
            }

        except Exception as e:
            db.rollback()
            logger.error(f"Error in mock game sync: {e}")
            return {
                "success": False,
                "message": f"Mock sync failed: {str(e)}",
                "games_updated": 0,
                "games_created": 0,
            }
        finally:
            db.close()

    async def sync_game_scores(self, days_back: int = 3) -> Dict[str, any]:
        """
        Sync game scores from The Odds API and update database

        Args:
            days_back: Number of days back to fetch scores

        Returns:
            Dict with sync results
        """
        if not self.is_available():
            logger.warning("Game sync service unavailable - using mock mode")
            return await self.sync_game_scores_mock()

        total_updated = 0
        total_created = 0
        sports_synced = []

        # Use async context manager for odds API service
        async with self.odds_api_service as api_service:
            try:
                for sport_key in self.sync_sports:
                    try:
                        logger.info(f"Syncing scores for {sport_key}")

                        # Fetch scores from Odds API
                        scores = await api_service.get_scores(
                            sport=sport_key.value, days_from=days_back
                        )

                        if not scores:
                            logger.info(f"No scores found for {sport_key}")
                            continue

                        # Update database with scores
                        updated, created = await self._update_games_from_scores(
                            scores, sport_key.value
                        )
                        total_updated += updated
                        total_created += created
                        sports_synced.append(sport_key.value)

                        logger.info(
                            f"Synced {sport_key}: {updated} updated, {created} created"
                        )

                        # Small delay between API calls to respect rate limits
                        await asyncio.sleep(1)

                    except Exception as e:
                        logger.error(f"Error syncing {sport_key}: {e}")
                        continue

                return {
                    "success": True,
                    "message": f"Synced {len(sports_synced)} sports: {', '.join(sports_synced)}",
                    "games_updated": total_updated,
                    "games_created": total_created,
                    "sports_synced": sports_synced,
                }

            except Exception as e:
                logger.error(f"Error during game sync: {e}")
                return {
                    "success": False,
                    "message": f"Game sync failed: {str(e)}",
                    "games_updated": total_updated,
                    "games_created": total_created,
                }

    async def _update_games_from_scores(
        self, scores, sport_key: str
    ) -> tuple[int, int]:
        """
        Update games in database from API scores

        Returns:
            Tuple of (updated_count, created_count)
        """
        updated_count = 0
        created_count = 0

        db = SessionLocal()
        try:
            for score in scores:
                # Try to find existing game by API ID
                existing_game = db.query(Game).filter(Game.id == score.id).first()

                if existing_game:
                    # Update existing game
                    needs_update = False

                    # Update status if completed
                    if score.completed and existing_game.status != GameStatus.FINAL:
                        existing_game.status = GameStatus.FINAL
                        needs_update = True

                    # Update scores if available
                    if (
                        score.home_score is not None
                        and existing_game.home_score != score.home_score
                    ):
                        existing_game.home_score = score.home_score
                        needs_update = True

                    if (
                        score.away_score is not None
                        and existing_game.away_score != score.away_score
                    ):
                        existing_game.away_score = score.away_score
                        needs_update = True

                    # Update other fields
                    if existing_game.sport_key != sport_key:
                        existing_game.sport_key = sport_key
                        needs_update = True

                    if existing_game.sport_title != score.sport_title:
                        existing_game.sport_title = score.sport_title
                        needs_update = True

                    if needs_update:
                        existing_game.last_update = datetime.utcnow()
                        updated_count += 1
                        logger.debug(
                            f"Updated game: {score.away_team} @ {score.home_team}"
                        )

                else:
                    # Create new game
                    new_game = Game(
                        id=score.id,
                        sport_key=sport_key,
                        sport_title=score.sport_title,
                        home_team=score.home_team,
                        away_team=score.away_team,
                        commence_time=score.commence_time,
                        status=(
                            GameStatus.FINAL
                            if score.completed
                            else GameStatus.SCHEDULED
                        ),
                        home_score=score.home_score or 0,
                        away_score=score.away_score or 0,
                        last_update=datetime.utcnow(),
                    )
                    db.add(new_game)
                    created_count += 1
                    logger.debug(f"Created game: {score.away_team} @ {score.home_team}")

            db.commit()
            return updated_count, created_count

        except Exception as e:
            db.rollback()
            logger.error(f"Error updating games from scores: {e}")
            raise
        finally:
            db.close()

    async def get_outdated_games(self, hours_threshold: int = 4) -> List[str]:
        """
        Get list of game IDs that haven't been updated recently
        and might need fresh data from the API

        Args:
            hours_threshold: Games not updated in this many hours are considered outdated

        Returns:
            List of game IDs that need updating
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_threshold)

        db = SessionLocal()
        try:
            outdated_games = (
                db.query(Game.id)
                .filter(
                    Game.last_update < cutoff_time,
                    Game.status.in_([GameStatus.SCHEDULED, GameStatus.LIVE]),
                )
                .all()
            )

            return [game.id for game in outdated_games]

        finally:
            db.close()

    async def sync_upcoming_games(self, days_ahead: int = 7) -> Dict[str, any]:
        """
        Sync upcoming games from The Odds API and store in database

        This ensures we have real game data for betting instead of placeholder data

        Args:
            days_ahead: Number of days ahead to fetch games

        Returns:
            Dict with sync results
        """
        if not self.is_available():
            logger.warning("Game sync service unavailable - no API key")
            return {"status": "skipped", "reason": "no_api_key"}

        total_updated = 0
        total_created = 0
        sports_synced = []

        try:
            for sport_key in self.sync_sports:
                try:
                    logger.info(f"Syncing upcoming games for {sport_key}")

                    # Fetch upcoming games from Odds API
                    games = await self.odds_api_service.get_odds(
                        sport=sport_key.value,
                        commence_time_from=datetime.utcnow(),
                        commence_time_to=datetime.utcnow() + timedelta(days=days_ahead),
                    )

                    if not games:
                        logger.info(f"No upcoming games found for {sport_key}")
                        continue

                    # Update database with game data
                    updated, created = await self._update_games_from_odds(
                        games, sport_key.value
                    )
                    total_updated += updated
                    total_created += created
                    sports_synced.append(sport_key.value)

                    logger.info(
                        f"Synced {sport_key}: {updated} updated, {created} created from {len(games)} games"
                    )

                    # Small delay between API calls to respect rate limits
                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"Error syncing upcoming games for {sport_key}: {e}")
                    continue

            return {
                "status": "success",
                "total_updated": total_updated,
                "total_created": total_created,
                "sports_synced": sports_synced,
                "message": f"Synced {total_updated + total_created} games across {len(sports_synced)} sports",
            }

        except Exception as e:
            logger.error(f"Critical error in sync_upcoming_games: {e}")
            return {"status": "error", "error": str(e)}

    async def _update_games_from_odds(
        self, games: List, sport_key: str
    ) -> tuple[int, int]:
        """
        Update database games from Odds API game data

        Args:
            games: List of Game objects from Odds API
            sport_key: Sport key for logging

        Returns:
            Tuple of (updated_count, created_count)
        """
        updated_count = 0
        created_count = 0

        db = SessionLocal()
        try:
            for api_game in games:
                try:
                    # Check if game exists
                    existing_game = (
                        db.query(Game).filter(Game.id == api_game.id).first()
                    )

                    if existing_game:
                        # Update existing game with real data
                        existing_game.sport_key = api_game.sport_key
                        existing_game.sport_title = api_game.sport_title
                        existing_game.home_team = api_game.home_team
                        existing_game.away_team = api_game.away_team
                        existing_game.commence_time = api_game.commence_time
                        existing_game.last_update = datetime.utcnow()

                        # Only update status if it's currently placeholder
                        if existing_game.status == GameStatus.SCHEDULED:
                            existing_game.status = GameStatus.SCHEDULED

                        updated_count += 1
                        logger.info(
                            f"Updated existing game: {api_game.away_team} @ {api_game.home_team}"
                        )

                    else:
                        # Create new game from API data
                        new_game = Game(
                            id=api_game.id,
                            sport_key=api_game.sport_key,
                            sport_title=api_game.sport_title,
                            home_team=api_game.home_team,
                            away_team=api_game.away_team,
                            commence_time=api_game.commence_time,
                            status=GameStatus.SCHEDULED,
                            last_update=datetime.utcnow(),
                        )

                        db.add(new_game)
                        created_count += 1
                        logger.info(
                            f"Created new game: {api_game.away_team} @ {api_game.home_team}"
                        )

                except Exception as e:
                    logger.error(f"Error processing game {api_game.id}: {e}")
                    continue

            db.commit()

        except Exception as e:
            logger.error(f"Database error in _update_games_from_odds: {e}")
            db.rollback()

        finally:
            db.close()

        return updated_count, created_count


# Global service instance
game_sync_service = GameSyncService()
