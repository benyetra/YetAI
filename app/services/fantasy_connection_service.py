"""
Fantasy Platform Connection Service
Handles connecting users to fantasy platforms and storing the connection info
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.services.sleeper_fantasy_service import SleeperFantasyService
from app.models.fantasy_models import FantasyPlatform

logger = logging.getLogger(__name__)

class FantasyConnectionService:
    """Service for connecting users to fantasy platforms"""

    def __init__(self):
        self.sleeper_service = SleeperFantasyService()

    async def connect_platform(self, user_id: int, platform: str, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """
        Connect a user to a fantasy platform

        Args:
            user_id: The internal user ID
            platform: The platform name (sleeper, espn, yahoo)
            credentials: Platform-specific credentials

        Returns:
            Connection result with status and details
        """
        try:
            if platform.lower() == "sleeper":
                return await self._connect_sleeper(user_id, credentials)
            else:
                raise ValueError(f"Unsupported platform: {platform}")

        except Exception as e:
            logger.error(f"Error connecting user {user_id} to {platform}: {e}")
            raise

    async def _connect_sleeper(self, user_id: int, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Connect user to Sleeper platform"""

        # Authenticate with Sleeper
        sleeper_user_data = await self.sleeper_service.authenticate_user(credentials)

        # Save to database
        db = SessionLocal()
        try:
            # Check if connection already exists
            from app.models.fantasy_models import FantasyUser
            existing_connection = db.query(FantasyUser).filter(
                FantasyUser.user_id == user_id,
                FantasyUser.platform == FantasyPlatform.SLEEPER
            ).first()

            if existing_connection:
                # Update existing connection
                existing_connection.platform_user_id = sleeper_user_data['user_id']
                existing_connection.platform_username = sleeper_user_data['username']
                existing_connection.is_active = True
                existing_connection.last_sync = None  # Reset sync status
                existing_connection.sync_error = None
                existing_connection.updated_at = datetime.now(timezone.utc)

                db.commit()
                logger.info(f"Updated existing Sleeper connection for user {user_id}")

                return {
                    "status": "success",
                    "connection": {
                        "platform": "sleeper",
                        "platform_user_id": sleeper_user_data['user_id'],
                        "platform_username": sleeper_user_data['username'],
                        "display_name": sleeper_user_data['display_name'],
                        "connected_at": existing_connection.updated_at.isoformat(),
                        "is_new_connection": False
                    },
                    "message": "Successfully updated Sleeper connection"
                }
            else:
                # Create new connection
                new_connection = FantasyUser(
                    user_id=user_id,
                    platform=FantasyPlatform.SLEEPER,
                    platform_user_id=sleeper_user_data['user_id'],
                    platform_username=sleeper_user_data['username'],
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )

                db.add(new_connection)
                db.commit()
                logger.info(f"Created new Sleeper connection for user {user_id}")

                return {
                    "status": "success",
                    "connection": {
                        "platform": "sleeper",
                        "platform_user_id": sleeper_user_data['user_id'],
                        "platform_username": sleeper_user_data['username'],
                        "display_name": sleeper_user_data['display_name'],
                        "connected_at": new_connection.created_at.isoformat(),
                        "is_new_connection": True
                    },
                    "message": "Successfully connected to Sleeper"
                }

        except Exception as db_error:
            db.rollback()
            logger.error(f"Database error saving Sleeper connection: {db_error}")
            raise
        finally:
            db.close()

    async def get_user_connections(self, user_id: int) -> Dict[str, Any]:
        """Get all fantasy platform connections for a user"""
        db = SessionLocal()
        try:
            from app.models.fantasy_models import FantasyUser
            connections = db.query(FantasyUser).filter(
                FantasyUser.user_id == user_id,
                FantasyUser.is_active == True
            ).all()

            result = []
            for conn in connections:
                result.append({
                    "id": conn.platform_user_id,  # For React key prop
                    "platform": conn.platform.value,
                    "platform_user_id": conn.platform_user_id,
                    "platform_username": conn.platform_username,
                    "user_id": conn.platform_user_id,  # For backwards compatibility with frontend
                    "username": conn.platform_username,  # For backwards compatibility with frontend
                    "connected_at": conn.created_at.isoformat() if conn.created_at else None,
                    "last_sync": conn.last_sync.isoformat() if conn.last_sync else None,
                    "status": "active"
                })

            return {
                "status": "success",
                "accounts": result,
                "message": f"Found {len(result)} active fantasy connections"
            }

        except Exception as e:
            logger.error(f"Error getting connections for user {user_id}: {e}")
            raise
        finally:
            db.close()

    async def get_user_leagues(self, user_id: int) -> Dict[str, Any]:
        """Get all fantasy leagues for a user's connected accounts"""
        db = SessionLocal()
        try:
            from app.models.fantasy_models import FantasyUser
            connections = db.query(FantasyUser).filter(
                FantasyUser.user_id == user_id,
                FantasyUser.is_active == True
            ).all()

            all_leagues = []

            for connection in connections:
                if connection.platform == FantasyPlatform.SLEEPER:
                    try:
                        # Get leagues from Sleeper API
                        leagues = await self.sleeper_service.get_user_leagues(connection.platform_user_id)

                        # Add platform info to each league
                        for league in leagues:
                            league['platform'] = 'sleeper'
                            league['fantasy_user_id'] = connection.id
                            league['platform_user_id'] = connection.platform_user_id
                            # Add id field for React key prop compatibility
                            league['id'] = league.get('league_id', league.get('id'))

                        all_leagues.extend(leagues)
                        logger.info(f"Found {len(leagues)} leagues for Sleeper user {connection.platform_username}")

                    except Exception as e:
                        logger.error(f"Error fetching leagues for Sleeper user {connection.platform_user_id}: {e}")
                        continue

            return {
                "status": "success",
                "leagues": all_leagues,
                "message": f"Found {len(all_leagues)} fantasy leagues"
            }

        except Exception as e:
            logger.error(f"Error getting leagues for user {user_id}: {e}")
            raise
        finally:
            db.close()

    async def disconnect_platform(self, user_id: int, platform_user_id: str) -> Dict[str, Any]:
        """Disconnect a fantasy platform connection"""
        db = SessionLocal()
        try:
            from app.models.fantasy_models import FantasyUser
            connection = db.query(FantasyUser).filter(
                FantasyUser.user_id == user_id,
                FantasyUser.platform_user_id == platform_user_id,
                FantasyUser.is_active == True
            ).first()

            if not connection:
                return {
                    "status": "error",
                    "message": "Fantasy connection not found"
                }

            # Deactivate the connection
            connection.is_active = False
            connection.updated_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(f"Disconnected {connection.platform.value} connection for user {user_id}")

            return {
                "status": "success",
                "message": f"Successfully disconnected {connection.platform.value} account"
            }

        except Exception as e:
            db.rollback()
            logger.error(f"Error disconnecting platform for user {user_id}: {e}")
            raise
        finally:
            db.close()

# Global instance
fantasy_connection_service = FantasyConnectionService()