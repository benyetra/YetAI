"""
Fantasy Pipeline Service
Basic fantasy football projections and player data
"""

import asyncio
import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from sqlalchemy.orm import Session

from app.services.fantasy_projections import generate_deterministic_projections

logger = logging.getLogger(__name__)


class FantasyPipeline:
    """Fantasy football pipeline for projections and player data"""

    def __init__(self):
        self.espn_base_url = "https://site.api.espn.com/apis/site/v2/sports"
        # Import here to avoid circular imports
        self._sleeper_service = None
        self._fantasy_connection_service = None

    async def get_nfl_players(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get NFL player data from Sleeper API"""
        try:
            # Import here to avoid circular imports
            if self._sleeper_service is None:
                from app.services.sleeper_fantasy_service import SleeperFantasyService

                self._sleeper_service = SleeperFantasyService()

            logger.info(f"Getting NFL players from Sleeper API (limit: {limit})")

            # Get all players from Sleeper
            all_players = await self._sleeper_service._get_all_players()

            if not all_players:
                logger.error("No players data available from Sleeper")
                return []

            # Convert to our format and limit results
            players = []
            count = 0
            for player_id, player_data in all_players.items():
                if count >= limit:
                    break

                if not player_data or not player_data.get("active"):
                    continue

                # Only include main fantasy positions
                position = player_data.get("position")
                if position not in ["QB", "RB", "WR", "TE", "K"]:
                    continue

                name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()
                if not name:
                    continue

                players.append(
                    {
                        "id": player_id,
                        "name": name,
                        "position": position,
                        "team": player_data.get("team", "FA"),
                        "age": player_data.get("age"),
                        "status": "active" if player_data.get("active") else "inactive",
                        "injury_status": player_data.get("injury_status"),
                    }
                )

                count += 1

            logger.info(f"Retrieved {len(players)} active NFL players from Sleeper")
            return players

        except Exception as e:
            logger.error(f"Error fetching NFL players from Sleeper: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    def generate_fantasy_projections(
        self,
        players: List[Dict],
        games: Optional[List[Dict]] = None,
        *,
        db: Optional[Session] = None,
        season: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Generate deterministic projections from analytics or position baselines."""
        season = season or datetime.now().year
        if db is not None:
            return generate_deterministic_projections(
                db, players, games or [], season=season, limit=50
            )
        return generate_deterministic_projections(
            None, players, games or [], season=season, limit=50
        )

    async def get_league_roster(
        self, league_id: str, user_id: int
    ) -> List[Dict[str, Any]]:
        """Get league roster for a specific user"""
        try:
            # Lazy import to avoid circular imports
            if self._sleeper_service is None:
                from app.services.sleeper_fantasy_service import SleeperFantasyService

                self._sleeper_service = SleeperFantasyService()

            if self._fantasy_connection_service is None:
                from app.services.fantasy_connection_service import (
                    fantasy_connection_service,
                )

                self._fantasy_connection_service = fantasy_connection_service

            logger.info(f"Getting roster for league {league_id}, user {user_id}")

            # Get user's fantasy connections
            connections_result = (
                await self._fantasy_connection_service.get_user_connections(user_id)
            )
            connections = connections_result.get("accounts", [])

            if not connections:
                logger.warning(f"No fantasy connections found for user {user_id}")
                return []

            # Find the Sleeper connection
            sleeper_connection = None
            for conn in connections:
                if conn.get("platform") == "sleeper":
                    sleeper_connection = conn
                    break

            if not sleeper_connection:
                logger.warning(f"No Sleeper connection found for user {user_id}")
                return []

            platform_user_id = sleeper_connection.get("platform_user_id")
            logger.info(
                f"Found Sleeper connection for user {user_id}: platform_user_id={platform_user_id}"
            )

            # Get roster for this user in this league
            roster_player_ids = await self._sleeper_service.get_roster_by_owner(
                league_id, platform_user_id
            )

            if not roster_player_ids:
                logger.warning(
                    f"No roster found for user {platform_user_id} in league {league_id}"
                )
                return []

            logger.info(f"Found {len(roster_player_ids)} players in roster")

            # Get player details
            all_players = await self._sleeper_service._get_all_players()

            roster_players = []
            for player_id in roster_player_ids:
                if player_id in all_players:
                    player_data = all_players[player_id]
                    roster_players.append(
                        {
                            "player_id": player_id,
                            "name": f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip(),
                            "position": player_data.get("position"),
                            "team": player_data.get("team"),
                            "status": (
                                "active" if player_data.get("active") else "inactive"
                            ),
                            "injury_status": player_data.get("injury_status"),
                            "fantasy_positions": player_data.get(
                                "fantasy_positions", []
                            ),
                        }
                    )
                else:
                    # Player not found in data, create minimal entry
                    roster_players.append(
                        {
                            "player_id": player_id,
                            "name": f"Player {player_id}",
                            "position": "UNKNOWN",
                            "team": "FA",
                            "status": "active",
                        }
                    )

            logger.info(f"Successfully processed {len(roster_players)} roster players")
            return roster_players

        except Exception as e:
            logger.error(f"Error getting league roster: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    def get_start_sit_advice(
        self, projections: List[Dict], position: str
    ) -> List[Dict[str, Any]]:
        """Get start/sit advice for specific position"""
        position_players = [p for p in projections if p["position"] == position]

        advice = []
        for i, player in enumerate(position_players[:20]):  # Top 20 for position
            if i < 5:
                recommendation = "START"
                confidence = "High"
            elif i < 12:
                recommendation = "CONSIDER"
                confidence = "Medium"
            else:
                recommendation = "SIT"
                confidence = "Low"

            advice.append(
                {
                    "player_name": player["player_name"],
                    "team": player["team"],
                    "opponent": player["opponent"],
                    "projected_points": player["projected_points"],
                    "recommendation": recommendation,
                    "confidence": confidence,
                    "reasoning": f"Projected for {player['projected_points']} points vs {player['opponent']}",
                }
            )

        return advice


# Create global instance
fantasy_pipeline = FantasyPipeline()
