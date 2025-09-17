"""
Simplified Sleeper Fantasy Sports Integration
Focused on the specific workflow requested:
1. Connect username -> get SleeperUserID
2. Get all league history (2020-2025)
3. Sync rosters and player data
"""

import httpx
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.core.database import get_db
from app.models.database_models import User, SleeperLeague, SleeperRoster, SleeperPlayer

logger = logging.getLogger(__name__)


class SimplifiedSleeperService:
    """Simplified Sleeper API integration service"""

    def __init__(self):
        self.base_url = "https://api.sleeper.app/v1"
        # Cache for player data
        self._players_cache = {}
        self._players_cache_time = None

    async def connect_sleeper_account(
        self, user_id: int, sleeper_username: str, db: Session
    ) -> Dict[str, Any]:
        """
        Step 1: Connect Sleeper account by username
        Gets SleeperUserID and saves it to the user record
        """
        try:
            # Get Sleeper user data
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/user/{sleeper_username}")
                response.raise_for_status()
                sleeper_user_data = response.json()

            sleeper_user_id = sleeper_user_data["user_id"]

            # Update user record with Sleeper user ID
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise ValueError(f"User {user_id} not found")

            user.sleeper_user_id = sleeper_user_id
            db.commit()

            logger.info(
                f"Connected Sleeper account for user {user_id}: {sleeper_username} -> {sleeper_user_id}"
            )

            return {
                "sleeper_user_id": sleeper_user_id,
                "username": sleeper_user_data["username"],
                "display_name": sleeper_user_data.get("display_name", sleeper_username),
                "avatar": sleeper_user_data.get("avatar"),
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError(f"Sleeper username '{sleeper_username}' not found")
            raise ValueError(f"Failed to connect Sleeper account: {e}")
        except Exception as e:
            logger.error(f"Error connecting Sleeper account: {str(e)}")
            raise ValueError(f"Connection failed: {str(e)}")

    async def sync_all_league_history(
        self, user_id: int, db: Session
    ) -> Dict[str, Any]:
        """
        Step 2: Sync all league history from 2020-2025
        Gets all leagues the user has participated in
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.sleeper_user_id:
            raise ValueError("User must have connected Sleeper account first")

        sleeper_user_id = user.sleeper_user_id
        current_year = datetime.now().year

        all_leagues = []
        synced_count = 0

        # Cycle through years 2020 to current year
        for year in range(2020, current_year + 1):
            try:
                logger.info(f"Syncing leagues for user {user_id}, season {year}")
                year_leagues = await self._get_user_leagues_for_season(
                    sleeper_user_id, year
                )

                for league_data in year_leagues:
                    # Check if league already exists
                    existing_league = (
                        db.query(SleeperLeague)
                        .filter(
                            and_(
                                SleeperLeague.user_id == user_id,
                                SleeperLeague.sleeper_league_id
                                == league_data["league_id"],
                                SleeperLeague.season == year,
                            )
                        )
                        .first()
                    )

                    if existing_league:
                        logger.debug(
                            f"League {league_data['league_id']} already exists for season {year}"
                        )
                        continue

                    # Create new league record
                    new_league = SleeperLeague(
                        user_id=user_id,
                        sleeper_league_id=league_data["league_id"],
                        name=league_data["name"],
                        season=year,
                        total_rosters=league_data["total_rosters"],
                        status=league_data.get("status", "complete"),
                        scoring_type=league_data.get("scoring_type", "standard"),
                        roster_positions=league_data.get("roster_positions", []),
                        scoring_settings=league_data.get("scoring_settings", {}),
                        waiver_settings=league_data.get("waiver_settings", {}),
                        last_synced=datetime.utcnow(),
                    )

                    db.add(new_league)
                    db.flush()  # Get the ID

                    all_leagues.append(
                        {
                            "id": new_league.id,
                            "sleeper_league_id": league_data["league_id"],
                            "name": league_data["name"],
                            "season": year,
                            "status": league_data.get("status", "complete"),
                        }
                    )

                    synced_count += 1

                    # Small delay to be nice to the API
                    await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Failed to sync leagues for season {year}: {str(e)}")
                continue

        db.commit()

        logger.info(f"Synced {synced_count} new leagues for user {user_id}")

        return {
            "synced_leagues": all_leagues,
            "total_synced": synced_count,
            "seasons_checked": list(range(2020, current_year + 1)),
        }

    async def sync_all_rosters(self, user_id: int, db: Session) -> Dict[str, Any]:
        """
        Step 3: Sync all rosters for all leagues
        Gets roster data for each league and saves to database
        """
        # Get all leagues for this user
        user_leagues = (
            db.query(SleeperLeague).filter(SleeperLeague.user_id == user_id).all()
        )

        total_rosters_synced = 0

        for league in user_leagues:
            try:
                logger.info(
                    f"Syncing rosters for league {league.sleeper_league_id} ({league.name})"
                )

                # Get rosters for this league
                rosters_data = await self._get_league_rosters(league.sleeper_league_id)

                for roster_data in rosters_data:
                    # Check if roster already exists
                    existing_roster = (
                        db.query(SleeperRoster)
                        .filter(
                            and_(
                                SleeperRoster.league_id == league.id,
                                SleeperRoster.sleeper_roster_id
                                == str(roster_data["roster_id"]),
                            )
                        )
                        .first()
                    )

                    if existing_roster:
                        # Update existing roster
                        existing_roster.wins = roster_data.get("settings", {}).get(
                            "wins", 0
                        )
                        existing_roster.losses = roster_data.get("settings", {}).get(
                            "losses", 0
                        )
                        existing_roster.ties = roster_data.get("settings", {}).get(
                            "ties", 0
                        )
                        existing_roster.points_for = float(
                            roster_data.get("settings", {}).get("fpts", 0)
                        )
                        existing_roster.points_against = float(
                            roster_data.get("settings", {}).get("fpts_against", 0)
                        )
                        existing_roster.waiver_position = roster_data.get(
                            "settings", {}
                        ).get("waiver_position")
                        existing_roster.players = roster_data.get("players", [])
                        existing_roster.starters = roster_data.get("starters", [])
                        existing_roster.last_synced = datetime.utcnow()
                    else:
                        # Create new roster
                        new_roster = SleeperRoster(
                            league_id=league.id,
                            sleeper_roster_id=str(roster_data["roster_id"]),
                            sleeper_owner_id=roster_data["owner_id"],
                            team_name=self._get_team_name_from_roster(roster_data),
                            owner_name="Unknown",  # Will be updated when we get user data
                            wins=roster_data.get("settings", {}).get("wins", 0),
                            losses=roster_data.get("settings", {}).get("losses", 0),
                            ties=roster_data.get("settings", {}).get("ties", 0),
                            points_for=float(
                                roster_data.get("settings", {}).get("fpts", 0)
                            ),
                            points_against=float(
                                roster_data.get("settings", {}).get("fpts_against", 0)
                            ),
                            waiver_position=roster_data.get("settings", {}).get(
                                "waiver_position"
                            ),
                            players=roster_data.get("players", []),
                            starters=roster_data.get("starters", []),
                            last_synced=datetime.utcnow(),
                        )

                        db.add(new_roster)
                        total_rosters_synced += 1

                await asyncio.sleep(0.1)  # Rate limiting

            except Exception as e:
                logger.error(
                    f"Failed to sync rosters for league {league.sleeper_league_id}: {str(e)}"
                )
                continue

        db.commit()

        logger.info(f"Synced {total_rosters_synced} rosters for user {user_id}")

        return {
            "total_rosters_synced": total_rosters_synced,
            "leagues_processed": len(user_leagues),
        }

    async def sync_nfl_players(self, db: Session) -> Dict[str, Any]:
        """
        Step 4: Sync all NFL player data
        Gets all NFL players from Sleeper and stores in database
        """
        try:
            logger.info("Starting NFL player sync")

            # Get all players from Sleeper
            players_data = await self._get_all_players()

            synced_count = 0
            updated_count = 0

            for player_id, player_data in players_data.items():
                try:
                    # Check if player already exists
                    existing_player = (
                        db.query(SleeperPlayer)
                        .filter(SleeperPlayer.sleeper_player_id == player_id)
                        .first()
                    )

                    if existing_player:
                        # Update existing player
                        existing_player.first_name = player_data.get("first_name")
                        existing_player.last_name = player_data.get("last_name")
                        existing_player.full_name = f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip()
                        existing_player.position = player_data.get("position")
                        existing_player.team = player_data.get("team")
                        existing_player.age = player_data.get("age")
                        existing_player.height = player_data.get("height")
                        existing_player.weight = player_data.get("weight")
                        existing_player.years_exp = player_data.get("years_exp")
                        existing_player.college = player_data.get("college")
                        existing_player.fantasy_positions = player_data.get(
                            "fantasy_positions", []
                        )
                        existing_player.status = player_data.get("status")
                        existing_player.injury_status = player_data.get("injury_status")
                        existing_player.depth_chart_position = player_data.get(
                            "depth_chart_position"
                        )
                        existing_player.depth_chart_order = player_data.get(
                            "depth_chart_order"
                        )
                        existing_player.search_rank = player_data.get("search_rank")
                        existing_player.hashtag = player_data.get("hashtag")
                        existing_player.espn_id = player_data.get("espn_id")
                        existing_player.yahoo_id = player_data.get("yahoo_id")
                        existing_player.fantasy_data_id = (
                            str(player_data.get("fantasy_data_id"))
                            if player_data.get("fantasy_data_id")
                            else None
                        )
                        existing_player.rotoworld_id = (
                            str(player_data.get("rotoworld_id"))
                            if player_data.get("rotoworld_id")
                            else None
                        )
                        existing_player.rotowire_id = (
                            str(player_data.get("rotowire_id"))
                            if player_data.get("rotowire_id")
                            else None
                        )
                        existing_player.sportradar_id = player_data.get("sportradar_id")
                        existing_player.stats_id = player_data.get("stats_id")
                        existing_player.last_synced = datetime.utcnow()
                        updated_count += 1
                    else:
                        # Create new player
                        new_player = SleeperPlayer(
                            sleeper_player_id=player_id,
                            first_name=player_data.get("first_name"),
                            last_name=player_data.get("last_name"),
                            full_name=f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip(),
                            position=player_data.get("position"),
                            team=player_data.get("team"),
                            age=player_data.get("age"),
                            height=player_data.get("height"),
                            weight=player_data.get("weight"),
                            years_exp=player_data.get("years_exp"),
                            college=player_data.get("college"),
                            fantasy_positions=player_data.get("fantasy_positions", []),
                            status=player_data.get("status"),
                            injury_status=player_data.get("injury_status"),
                            depth_chart_position=player_data.get(
                                "depth_chart_position"
                            ),
                            depth_chart_order=player_data.get("depth_chart_order"),
                            search_rank=player_data.get("search_rank"),
                            hashtag=player_data.get("hashtag"),
                            espn_id=player_data.get("espn_id"),
                            yahoo_id=player_data.get("yahoo_id"),
                            fantasy_data_id=(
                                str(player_data.get("fantasy_data_id"))
                                if player_data.get("fantasy_data_id")
                                else None
                            ),
                            rotoworld_id=(
                                str(player_data.get("rotoworld_id"))
                                if player_data.get("rotoworld_id")
                                else None
                            ),
                            rotowire_id=(
                                str(player_data.get("rotowire_id"))
                                if player_data.get("rotowire_id")
                                else None
                            ),
                            sportradar_id=player_data.get("sportradar_id"),
                            stats_id=player_data.get("stats_id"),
                            last_synced=datetime.utcnow(),
                        )

                        db.add(new_player)
                        synced_count += 1

                    # Commit every 100 players to avoid large transactions
                    if (synced_count + updated_count) % 100 == 0:
                        db.commit()

                except Exception as e:
                    logger.error(f"Failed to process player {player_id}: {str(e)}")
                    continue

            db.commit()

            logger.info(
                f"NFL player sync complete: {synced_count} new, {updated_count} updated"
            )

            return {
                "new_players": synced_count,
                "updated_players": updated_count,
                "total_processed": synced_count + updated_count,
            }

        except Exception as e:
            logger.error(f"Failed to sync NFL players: {str(e)}")
            raise ValueError(f"Player sync failed: {str(e)}")

    async def full_sync_workflow(
        self, user_id: int, sleeper_username: str, db: Session
    ) -> Dict[str, Any]:
        """
        Complete workflow: Connect account -> Sync leagues -> Sync rosters -> Sync players
        """
        try:
            logger.info(
                f"Starting full Sleeper sync for user {user_id} with username {sleeper_username}"
            )

            # Step 1: Connect account
            connect_result = await self.connect_sleeper_account(
                user_id, sleeper_username, db
            )

            # Step 2: Sync league history
            leagues_result = await self.sync_all_league_history(user_id, db)

            # Step 3: Sync rosters
            rosters_result = await self.sync_all_rosters(user_id, db)

            # Step 4: Sync players (only if we don't have recent data)
            players_result = await self.sync_nfl_players(db)

            return {
                "success": True,
                "connect_result": connect_result,
                "leagues_result": leagues_result,
                "rosters_result": rosters_result,
                "players_result": players_result,
                "message": "Full Sleeper sync completed successfully",
            }

        except Exception as e:
            logger.error(f"Full sync workflow failed: {str(e)}")
            raise ValueError(f"Sync workflow failed: {str(e)}")

    # Helper methods

    async def _get_user_leagues_for_season(
        self, sleeper_user_id: str, season: int
    ) -> List[Dict[str, Any]]:
        """Get all leagues for a user for a specific season"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/user/{sleeper_user_id}/leagues/nfl/{season}"
                )
                response.raise_for_status()

                leagues_data = response.json()

                processed_leagues = []
                for league in leagues_data:
                    processed_leagues.append(
                        {
                            "league_id": league["league_id"],
                            "name": league["name"],
                            "total_rosters": league["total_rosters"],
                            "status": league.get("status", "complete"),
                            "scoring_type": self._determine_scoring_type(league),
                            "roster_positions": league.get("roster_positions", []),
                            "scoring_settings": league.get("scoring_settings", {}),
                            "waiver_settings": league.get("settings", {}),
                        }
                    )

                return processed_leagues

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # No leagues for this season
                return []
            raise
        except Exception as e:
            logger.error(f"Error getting leagues for season {season}: {str(e)}")
            return []

    async def _get_league_rosters(self, league_id: str) -> List[Dict[str, Any]]:
        """Get all rosters for a league"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/league/{league_id}/rosters"
                )
                response.raise_for_status()

                return response.json()

        except Exception as e:
            logger.error(f"Error getting rosters for league {league_id}: {str(e)}")
            return []

    async def _get_all_players(self) -> Dict[str, Any]:
        """Get all NFL players data with caching"""
        # Check if cache is valid (refresh daily)
        now = datetime.now()
        if (
            self._players_cache_time
            and (now - self._players_cache_time).seconds < 86400
            and self._players_cache
        ):
            return self._players_cache

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(f"{self.base_url}/players/nfl")

                # Handle 304 Not Modified - data hasn't changed
                if response.status_code == 304:
                    logger.info(
                        "NFL players data not modified (304), using cached data"
                    )
                    if self._players_cache:
                        return self._players_cache
                    else:
                        # If we don't have cache but got 304, make request without ETag
                        response = await client.get(f"{self.base_url}/players/nfl")
                        response.raise_for_status()

                response.raise_for_status()

                self._players_cache = response.json()
                self._players_cache_time = now

                return self._players_cache

        except Exception as e:
            logger.error(f"Failed to get all players: {str(e)}")
            return self._players_cache if self._players_cache else {}

    def _determine_scoring_type(self, league_data: Dict[str, Any]) -> str:
        """Determine scoring type from league settings"""
        scoring_settings = league_data.get("scoring_settings", {})

        # Check for PPR scoring
        rec_points = scoring_settings.get("rec", 0)
        if rec_points >= 1:
            return "ppr"
        elif rec_points >= 0.5:
            return "half_ppr"
        else:
            return "standard"

    def _get_team_name_from_roster(self, roster_data: Dict[str, Any]) -> str:
        """Extract team name from roster data"""
        metadata = roster_data.get("metadata", {})
        if isinstance(metadata, dict):
            team_name = metadata.get("team_name")
            if team_name:
                return team_name

        # Fallback to roster ID
        return f"Team {roster_data.get('roster_id', 'Unknown')}"
