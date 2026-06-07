"""
Fantasy Platform Connection Service
Handles connecting users to fantasy platforms and storing the connection info
"""

import logging
from typing import Dict, Any

from app.services.fantasy_sleeper_unified import fantasy_sleeper_unified

logger = logging.getLogger(__name__)


class FantasyConnectionService:
    """Service for connecting users to fantasy platforms."""

    async def connect_platform(
        self, user_id: int, platform: str, credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            if platform.lower() != "sleeper":
                raise ValueError(f"Unsupported platform: {platform}")

            username = credentials.get("username")
            if not username:
                raise ValueError("Username is required for Sleeper")

            return await fantasy_sleeper_unified.connect(user_id, username)
        except Exception as e:
            logger.error(f"Error connecting user {user_id} to {platform}: {e}")
            raise

    async def get_user_connections(self, user_id: int) -> Dict[str, Any]:
        try:
            return fantasy_sleeper_unified.get_connections(user_id)
        except Exception as e:
            logger.error(f"Error getting connections for user {user_id}: {e}")
            raise

    async def get_user_leagues(self, user_id: int) -> Dict[str, Any]:
        try:
            return await fantasy_sleeper_unified.get_leagues(user_id)
        except Exception as e:
            logger.error(f"Error getting leagues for user {user_id}: {e}")
            raise

    async def sync_league(self, user_id: int, league_id: str) -> Dict[str, Any]:
        try:
            return await fantasy_sleeper_unified.sync_league(user_id, league_id)
        except Exception as e:
            logger.error(f"Error syncing league {league_id} for user {user_id}: {e}")
            raise

    async def sync_all_leagues(self, user_id: int) -> Dict[str, Any]:
        try:
            return await fantasy_sleeper_unified.sync_all_leagues(user_id)
        except Exception as e:
            logger.error(f"Error syncing leagues for user {user_id}: {e}")
            raise

    async def disconnect_platform(
        self, user_id: int, platform_user_id: str
    ) -> Dict[str, Any]:
        try:
            return await fantasy_sleeper_unified.disconnect(user_id, platform_user_id)
        except Exception as e:
            logger.error(f"Error disconnecting platform for user {user_id}: {e}")
            raise


fantasy_connection_service = FantasyConnectionService()
