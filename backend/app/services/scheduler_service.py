"""
Scheduler Service for automated data updates.

This service manages scheduled tasks for updating sports data, odds, and scores
from The Odds API at regular intervals.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from app.services.odds_api_service import OddsAPIService, SportKey
from app.services.cache_service import cache_service
from app.core.config import settings

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task execution status"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScheduledTask:
    """Represents a scheduled task"""

    name: str
    func: Callable
    interval_seconds: int
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    error_count: int = 0
    max_errors: int = 5
    enabled: bool = True


class SchedulerService:
    """Service for managing scheduled data updates"""

    def __init__(self):
        self.tasks: Dict[str, ScheduledTask] = {}
        self.running = False
        self.scheduler_task: Optional[asyncio.Task] = None
        self._setup_default_tasks()

    def _setup_default_tasks(self):
        """Set up default scheduled tasks with rate-limit friendly intervals"""
        # Update popular sports odds every 2 hours (conservative to stay under rate limits)
        self.add_task(
            "update_popular_odds",
            self._update_popular_sports_odds,
            interval_seconds=7200,  # 2 hours
        )

        # Update sports list every 6 hours (sports don't change often)
        self.add_task(
            "update_sports_list",
            self._update_sports_list,
            interval_seconds=21600,  # 6 hours
        )

        # Update live games every 30 minutes (much more conservative)
        self.add_task(
            "update_live_games",
            self._update_live_games,
            interval_seconds=1800,  # 30 minutes
        )

        # Update scores every 4 hours (scores don't change that often for completed games)
        self.add_task(
            "update_scores", self._update_scores, interval_seconds=14400  # 4 hours
        )

        # Clean up old cache entries every 30 minutes
        self.add_task(
            "cache_cleanup", self._cleanup_cache, interval_seconds=1800  # 30 minutes
        )

    def add_task(
        self,
        name: str,
        func: Callable,
        interval_seconds: int,
        max_errors: int = 5,
        enabled: bool = True,
    ):
        """Add a new scheduled task"""
        task = ScheduledTask(
            name=name,
            func=func,
            interval_seconds=interval_seconds,
            max_errors=max_errors,
            enabled=enabled,
        )

        # Set initial next run time
        task.next_run = datetime.utcnow() + timedelta(seconds=interval_seconds)

        self.tasks[name] = task
        logger.info(f"Added scheduled task: {name} (interval: {interval_seconds}s)")

    def remove_task(self, name: str):
        """Remove a scheduled task"""
        if name in self.tasks:
            del self.tasks[name]
            logger.info(f"Removed scheduled task: {name}")

    def enable_task(self, name: str):
        """Enable a scheduled task"""
        if name in self.tasks:
            self.tasks[name].enabled = True
            logger.info(f"Enabled task: {name}")

    def disable_task(self, name: str):
        """Disable a scheduled task"""
        if name in self.tasks:
            self.tasks[name].enabled = False
            logger.info(f"Disabled task: {name}")

    async def start(self):
        """Start the scheduler"""
        if self.running:
            logger.warning("Scheduler is already running")
            return

        self.running = True
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler started")

    async def stop(self):
        """Stop the scheduler"""
        if not self.running:
            return

        self.running = False

        if self.scheduler_task:
            self.scheduler_task.cancel()
            try:
                await self.scheduler_task
            except asyncio.CancelledError:
                pass

        logger.info("Scheduler stopped")

    async def _scheduler_loop(self):
        """Main scheduler loop"""
        logger.info("Scheduler loop started")

        while self.running:
            try:
                await self._process_tasks()
                await asyncio.sleep(10)  # Check every 10 seconds

            except asyncio.CancelledError:
                logger.info("Scheduler loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(30)  # Wait before retrying

    async def _process_tasks(self):
        """Process all scheduled tasks"""
        now = datetime.utcnow()

        for task_name, task in self.tasks.items():
            if not task.enabled:
                continue

            if task.status == TaskStatus.RUNNING:
                continue

            if task.error_count >= task.max_errors:
                logger.warning(f"Task {task_name} disabled due to too many errors")
                task.enabled = False
                continue

            if task.next_run and now >= task.next_run:
                # Run the task
                asyncio.create_task(self._execute_task(task))

    async def _execute_task(self, task: ScheduledTask):
        """Execute a single task"""
        logger.info(f"Executing task: {task.name}")

        task.status = TaskStatus.RUNNING
        task.last_run = datetime.utcnow()

        try:
            await task.func()
            task.status = TaskStatus.COMPLETED
            task.error_count = 0  # Reset error count on success
            logger.info(f"Task completed successfully: {task.name}")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_count += 1
            logger.error(f"Task failed: {task.name} - {e}")

        finally:
            # Schedule next run
            task.next_run = datetime.utcnow() + timedelta(seconds=task.interval_seconds)

    # Task implementations

    async def _update_popular_sports_odds(self):
        """Update odds for popular sports"""
        if not settings.ODDS_API_KEY:
            logger.warning("No Odds API key configured, skipping odds update")
            return

        popular_sports = [
            SportKey.AMERICANFOOTBALL_NFL,
            SportKey.BASKETBALL_NBA,
            SportKey.BASEBALL_MLB,
            SportKey.ICEHOCKEY_NHL,
        ]

        updated_count = 0

        async with OddsAPIService(settings.ODDS_API_KEY) as service:
            for i, sport in enumerate(popular_sports):
                try:
                    # Get odds for this sport
                    games = await service.get_odds(sport.value)

                    if games:
                        # Store in cache with standard format
                        result = {
                            "status": "success",
                            "sport": sport.value,
                            "count": len(games),
                            "games": [
                                {
                                    "id": game.id,
                                    "sport_key": game.sport_key,
                                    "sport_title": game.sport_title,
                                    "commence_time": game.commence_time.isoformat(),
                                    "home_team": game.home_team,
                                    "away_team": game.away_team,
                                    "bookmakers": [
                                        {
                                            "key": bm.key,
                                            "title": bm.title,
                                            "last_update": bm.last_update.isoformat(),
                                            "markets": bm.markets,
                                        }
                                        for bm in game.bookmakers
                                    ],
                                }
                                for game in games
                            ],
                            "last_updated": datetime.utcnow().isoformat(),
                            "cached": False,
                        }

                        # Cache with 2-hour expiry (much longer to reduce API calls)
                        await cache_service.set_odds(
                            sport.value,
                            "us",
                            "h2h,spreads,totals",
                            "american",
                            result,
                            expire_seconds=7200,
                        )

                        updated_count += 1
                        logger.info(
                            f"Updated odds for {sport.value}: {len(games)} games"
                        )

                except Exception as e:
                    logger.error(f"Failed to update odds for {sport.value}: {e}")
                    continue

                # Add delay between API calls to avoid rate limiting (except after last sport)
                if i < len(popular_sports) - 1:
                    await asyncio.sleep(1.5)  # 1.5 second delay between sports

        logger.info(
            f"Completed popular sports odds update: {updated_count} sports updated"
        )

    async def _update_sports_list(self):
        """Update the list of available sports"""
        if not settings.ODDS_API_KEY:
            logger.warning("No Odds API key configured, skipping sports list update")
            return

        try:
            async with OddsAPIService(settings.ODDS_API_KEY) as service:
                sports = await service.get_sports()

                # Filter to active sports and add categories
                active_sports = []
                for sport in sports:
                    if sport.get("active", False):
                        category = "Other"
                        if "football" in sport["key"].lower():
                            category = "Football"
                        elif "basketball" in sport["key"].lower():
                            category = "Basketball"
                        elif "baseball" in sport["key"].lower():
                            category = "Baseball"
                        elif "hockey" in sport["key"].lower():
                            category = "Hockey"
                        elif "soccer" in sport["key"].lower():
                            category = "Soccer"
                        elif "tennis" in sport["key"].lower():
                            category = "Tennis"
                        elif "golf" in sport["key"].lower():
                            category = "Golf"
                        elif (
                            "mma" in sport["key"].lower()
                            or "boxing" in sport["key"].lower()
                        ):
                            category = "Combat Sports"

                        sport["category"] = category
                        active_sports.append(sport)

                result = {
                    "status": "success",
                    "count": len(active_sports),
                    "sports": active_sports,
                    "last_updated": datetime.utcnow().isoformat(),
                    "cached": False,
                }

                # Cache for 6 hours (same as refresh interval)
                await cache_service.set_sports_list(result, expire_seconds=21600)
                logger.info(f"Updated sports list: {len(active_sports)} active sports")

        except Exception as e:
            logger.error(f"Failed to update sports list: {e}")
            raise

    async def _update_live_games(self):
        """Update live/upcoming games"""
        if not settings.ODDS_API_KEY:
            logger.warning("No Odds API key configured, skipping live games update")
            return

        try:
            from app.services.odds_api_service import get_live_games

            games = await get_live_games()

            if games:
                # Convert to cacheable format
                games_data = []
                for game in games:
                    bookmakers_data = []
                    for bookmaker in game.bookmakers:
                        bookmakers_data.append(
                            {
                                "key": bookmaker.key,
                                "title": bookmaker.title,
                                "last_update": bookmaker.last_update.isoformat(),
                                "markets": bookmaker.markets,
                            }
                        )

                    games_data.append(
                        {
                            "id": game.id,
                            "sport_key": game.sport_key,
                            "sport_title": game.sport_title,
                            "commence_time": game.commence_time.isoformat(),
                            "home_team": game.home_team,
                            "away_team": game.away_team,
                            "bookmakers": bookmakers_data,
                        }
                    )

                # Store in a special cache key for live games
                live_games_key = "odds_api:live_games:all"
                result = {
                    "status": "success",
                    "count": len(games_data),
                    "games": games_data,
                    "description": "Games starting within the next 2 hours",
                    "last_updated": datetime.utcnow().isoformat(),
                    "cached": False,
                }

                await cache_service.set(
                    live_games_key, result, expire_seconds=1800
                )  # 30 minutes
                logger.info(f"Updated live games: {len(games)} games")

        except Exception as e:
            logger.error(f"Failed to update live games: {e}")
            raise

    async def _update_scores(self):
        """Update game scores"""
        if not settings.ODDS_API_KEY:
            logger.warning("No Odds API key configured, skipping scores update")
            return

        sports_to_check = [
            SportKey.AMERICANFOOTBALL_NFL,
            SportKey.BASKETBALL_NBA,
            SportKey.BASEBALL_MLB,
            SportKey.ICEHOCKEY_NHL,
        ]

        updated_count = 0

        async with OddsAPIService(settings.ODDS_API_KEY) as service:
            for i, sport in enumerate(sports_to_check):
                try:
                    scores = await service.get_scores(sport.value, days_from=1)

                    if scores:
                        # Convert to cacheable format
                        scores_data = []
                        for score in scores:
                            scores_data.append(
                                {
                                    "id": score.id,
                                    "sport_key": score.sport_key,
                                    "sport_title": score.sport_title,
                                    "commence_time": score.commence_time.isoformat(),
                                    "home_team": score.home_team,
                                    "away_team": score.away_team,
                                    "completed": score.completed,
                                    "home_score": score.home_score,
                                    "away_score": score.away_score,
                                    "last_update": score.last_update.isoformat(),
                                }
                            )

                        result = {
                            "status": "success",
                            "sport": sport.value,
                            "days_from": 1,
                            "count": len(scores_data),
                            "scores": scores_data,
                            "last_updated": datetime.utcnow().isoformat(),
                            "cached": False,
                        }

                        # Cache scores for 4 hours (same as refresh interval)
                        await cache_service.set_scores(
                            sport.value, 1, result, expire_seconds=14400
                        )

                        updated_count += 1
                        logger.info(
                            f"Updated scores for {sport.value}: {len(scores)} games"
                        )

                except Exception as e:
                    logger.error(f"Failed to update scores for {sport.value}: {e}")
                    continue

                # Add delay between API calls to avoid rate limiting (except after last sport)
                if i < len(sports_to_check) - 1:
                    await asyncio.sleep(1.5)  # 1.5 second delay between sports

        logger.info(f"Completed scores update: {updated_count} sports updated")

    async def _cleanup_cache(self):
        """Clean up old cache entries"""
        try:
            # This is handled automatically by the cache service
            # We can add specific cleanup logic here if needed
            stats = await cache_service.get_cache_stats()
            logger.info(f"Cache cleanup completed. Stats: {stats}")

        except Exception as e:
            logger.error(f"Failed to cleanup cache: {e}")
            raise

    def get_task_status(self) -> Dict[str, Dict]:
        """Get status of all scheduled tasks"""
        status = {}

        for name, task in self.tasks.items():
            status[name] = {
                "name": task.name,
                "enabled": task.enabled,
                "status": task.status.value,
                "interval_seconds": task.interval_seconds,
                "last_run": task.last_run.isoformat() if task.last_run else None,
                "next_run": task.next_run.isoformat() if task.next_run else None,
                "error_count": task.error_count,
                "max_errors": task.max_errors,
            }

        return status

    async def run_task_now(self, task_name: str):
        """Manually trigger a task to run immediately"""
        if task_name not in self.tasks:
            raise ValueError(f"Task not found: {task_name}")

        task = self.tasks[task_name]
        if task.status == TaskStatus.RUNNING:
            raise ValueError(f"Task is already running: {task_name}")

        logger.info(f"Manually triggering task: {task_name}")
        await self._execute_task(task)


# Global scheduler instance
scheduler_service = SchedulerService()
