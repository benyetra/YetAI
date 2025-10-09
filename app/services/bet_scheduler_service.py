"""
Bet Scheduler Service - Handles periodic bet verification tasks

This service manages:
1. Scheduled bet verification runs
2. Background task management
3. Error handling and retries
4. Performance monitoring
5. Rate limiting for API calls
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from dataclasses import dataclass, asdict
import json

from app.services.unified_bet_verification_service import (
    unified_bet_verification_service,
)

logger = logging.getLogger(__name__)


@dataclass
class ScheduleConfig:
    """Configuration for scheduled verification"""

    enabled: bool = True
    interval_minutes: int = 15  # Run every 15 minutes
    retry_interval_minutes: int = 5  # Retry failed runs after 5 minutes
    max_retries: int = 3
    quiet_hours_start: int = 2  # 2 AM
    quiet_hours_end: int = 6  # 6 AM (UTC)
    rate_limit_delay: int = 1  # Seconds between API calls


@dataclass
class ScheduleStats:
    """Statistics for scheduled runs"""

    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    last_run_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    last_error: Optional[str] = None
    total_bets_verified: int = 0
    total_bets_settled: int = 0


class BetSchedulerService:
    """Service for managing scheduled bet verification"""

    def __init__(self, config: Optional[ScheduleConfig] = None):
        self.config = config or ScheduleConfig()
        self.stats = ScheduleStats()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._running = False

    def start(self) -> None:
        """Start the scheduled bet verification"""
        if self._running:
            logger.warning("Bet scheduler is already running")
            return

        if not self.config.enabled:
            logger.info("Bet scheduler is disabled in configuration")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_schedule())
        self._running = True
        logger.info(
            f"Started bet verification scheduler (interval: {self.config.interval_minutes} minutes)"
        )

    def stop(self) -> None:
        """Stop the scheduled bet verification"""
        if not self._running:
            return

        self._stop_event.set()
        if self._task:
            self._task.cancel()
        self._running = False
        logger.info("Stopped bet verification scheduler")

    async def _run_schedule(self) -> None:
        """Main scheduling loop"""
        logger.info("Bet verification scheduler started")

        while not self._stop_event.is_set():
            try:
                # Check if we're in quiet hours
                if self._is_quiet_hours():
                    logger.debug("Skipping verification during quiet hours")
                    await asyncio.sleep(60)  # Check every minute during quiet hours
                    continue

                # Run verification
                await self._run_verification()

                # Wait for next interval
                await asyncio.sleep(self.config.interval_minutes * 60)

            except asyncio.CancelledError:
                logger.info("Bet scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                # Wait for retry interval on error
                await asyncio.sleep(self.config.retry_interval_minutes * 60)

    def _is_quiet_hours(self) -> bool:
        """Check if current time is during quiet hours (UTC)"""
        now = datetime.utcnow()
        current_hour = now.hour

        if self.config.quiet_hours_start <= self.config.quiet_hours_end:
            # Normal range (e.g., 2 AM to 6 AM)
            return (
                self.config.quiet_hours_start
                <= current_hour
                < self.config.quiet_hours_end
            )
        else:
            # Wrap around range (e.g., 11 PM to 6 AM)
            return (
                current_hour >= self.config.quiet_hours_start
                or current_hour < self.config.quiet_hours_end
            )

    async def _run_verification(self) -> Dict:
        """Run bet verification with error handling and retries"""
        self.stats.total_runs += 1
        self.stats.last_run_time = datetime.utcnow()

        retries = 0
        last_error = None

        while retries <= self.config.max_retries:
            try:
                logger.info(
                    f"Starting bet verification run {self.stats.total_runs} (attempt {retries + 1})"
                )

                # Rate limiting delay
                if retries > 0:
                    await asyncio.sleep(self.config.rate_limit_delay)

                # Run the unified verification (uses API directly)
                result = (
                    await unified_bet_verification_service.verify_all_pending_bets()
                )

                if result.get("success", False):
                    # Success
                    self.stats.successful_runs += 1
                    self.stats.last_success_time = datetime.utcnow()
                    self.stats.last_error = None

                    # Update cumulative stats
                    self.stats.total_bets_verified += result.get("verified", 0)
                    self.stats.total_bets_settled += result.get("settled", 0)

                    logger.info(
                        f"Verification run completed successfully: {result.get('message', 'No message')}"
                    )

                    # Log detailed results
                    if result.get("verified", 0) > 0:
                        logger.info(
                            f"Verification stats: {result.get('verified')} verified, {result.get('settled')} settled, {result.get('games_checked')} games checked"
                        )

                    return result
                else:
                    # Service returned error
                    error_msg = result.get("error", "Unknown error")
                    logger.error(f"Verification service returned error: {error_msg}")
                    last_error = error_msg
                    retries += 1

                    if retries <= self.config.max_retries:
                        wait_time = (
                            self.config.retry_interval_minutes * 60 * retries
                        )  # Exponential backoff
                        logger.info(f"Retrying verification in {wait_time} seconds...")
                        await asyncio.sleep(wait_time)

            except asyncio.CancelledError:
                logger.info("Verification run cancelled")
                raise
            except Exception as e:
                logger.error(f"Error during verification run: {e}")
                last_error = str(e)
                retries += 1

                if retries <= self.config.max_retries:
                    wait_time = self.config.retry_interval_minutes * 60 * retries
                    logger.info(f"Retrying verification in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)

        # All retries failed
        self.stats.failed_runs += 1
        self.stats.last_error = last_error
        logger.error(
            f"Verification run failed after {self.config.max_retries} retries. Last error: {last_error}"
        )

        return {
            "success": False,
            "error": f"Failed after {self.config.max_retries} retries: {last_error}",
            "verified": 0,
            "settled": 0,
        }

    async def run_verification_now(self) -> Dict:
        """Manually trigger a verification run (for admin/testing)"""
        logger.info("Manual bet verification triggered")
        return await self._run_verification()

    def get_stats(self) -> Dict:
        """Get scheduler statistics"""
        return {
            "config": asdict(self.config),
            "stats": asdict(self.stats),
            "status": {
                "running": self._running,
                "in_quiet_hours": self._is_quiet_hours(),
                "next_run_estimate": self._get_next_run_estimate(),
            },
        }

    def _get_next_run_estimate(self) -> Optional[str]:
        """Estimate when the next run will occur"""
        if not self._running:
            return None

        if self._is_quiet_hours():
            # Next run is when quiet hours end
            now = datetime.utcnow()
            if self.config.quiet_hours_start <= self.config.quiet_hours_end:
                # Normal range
                next_run = now.replace(
                    hour=self.config.quiet_hours_end, minute=0, second=0, microsecond=0
                )
                if next_run <= now:
                    next_run += timedelta(days=1)
            else:
                # Wrap around range
                next_run = now.replace(
                    hour=self.config.quiet_hours_end, minute=0, second=0, microsecond=0
                )
                if now.hour >= self.config.quiet_hours_start:
                    next_run += timedelta(days=1)
        else:
            # Next run is after the interval
            if self.stats.last_run_time:
                next_run = self.stats.last_run_time + timedelta(
                    minutes=self.config.interval_minutes
                )
            else:
                next_run = datetime.utcnow()

        return next_run.isoformat()

    def update_config(self, new_config: Dict) -> Dict:
        """Update scheduler configuration"""
        try:
            # Validate and update config
            if "enabled" in new_config:
                self.config.enabled = bool(new_config["enabled"])
            if "interval_minutes" in new_config:
                interval = int(new_config["interval_minutes"])
                if interval < 1:
                    raise ValueError("Interval must be at least 1 minute")
                self.config.interval_minutes = interval
            if "retry_interval_minutes" in new_config:
                retry_interval = int(new_config["retry_interval_minutes"])
                if retry_interval < 1:
                    raise ValueError("Retry interval must be at least 1 minute")
                self.config.retry_interval_minutes = retry_interval
            if "max_retries" in new_config:
                max_retries = int(new_config["max_retries"])
                if max_retries < 0:
                    raise ValueError("Max retries cannot be negative")
                self.config.max_retries = max_retries
            if "quiet_hours_start" in new_config:
                quiet_start = int(new_config["quiet_hours_start"])
                if not (0 <= quiet_start <= 23):
                    raise ValueError("Quiet hours start must be between 0 and 23")
                self.config.quiet_hours_start = quiet_start
            if "quiet_hours_end" in new_config:
                quiet_end = int(new_config["quiet_hours_end"])
                if not (0 <= quiet_end <= 23):
                    raise ValueError("Quiet hours end must be between 0 and 23")
                self.config.quiet_hours_end = quiet_end

            logger.info(f"Scheduler configuration updated: {new_config}")

            # Restart scheduler if it was running
            if self._running and self.config.enabled:
                self.stop()
                import time

                time.sleep(1)  # Brief pause
                self.start()
            elif self._running and not self.config.enabled:
                self.stop()
            elif not self._running and self.config.enabled:
                self.start()

            return {"success": True, "message": "Configuration updated successfully"}

        except Exception as e:
            logger.error(f"Error updating scheduler config: {e}")
            return {"success": False, "error": str(e)}

    def reset_stats(self) -> Dict:
        """Reset scheduler statistics"""
        self.stats = ScheduleStats()
        logger.info("Scheduler statistics reset")
        return {"success": True, "message": "Statistics reset successfully"}


# Global scheduler instance
bet_scheduler = BetSchedulerService()


# Auto-start scheduler on import (can be disabled in config)
def init_scheduler():
    """Initialize the scheduler (called from main.py)"""
    try:
        bet_scheduler.start()
        logger.info("Bet verification scheduler initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize bet verification scheduler: {e}")


# Cleanup function
def cleanup_scheduler():
    """Cleanup scheduler (called from main.py shutdown)"""
    try:
        bet_scheduler.stop()
        logger.info("Bet verification scheduler stopped successfully")
    except Exception as e:
        logger.error(f"Error stopping bet verification scheduler: {e}")
