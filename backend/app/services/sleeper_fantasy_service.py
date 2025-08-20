"""
Sleeper Fantasy Sports API Integration
"""
import httpx
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from app.services.fantasy_service import FantasyPlatformInterface
from app.models.fantasy_models import FantasyPlatform

logger = logging.getLogger(__name__)

class SleeperFantasyService(FantasyPlatformInterface):
    """Sleeper API integration service"""
    
    def __init__(self):
        self.base_url = "https://api.sleeper.app/v1"
        self.platform = FantasyPlatform.SLEEPER
        # Cache for player data (updated daily)
        self._players_cache = {}
        self._players_cache_time = None
    
    async def authenticate_user(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """
        Authenticate user with Sleeper (no authentication required, just verify username)
        credentials should contain: {'username': 'sleeper_username'}
        """
        username = credentials.get('username')
        if not username:
            raise ValueError("Username is required for Sleeper")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/user/{username}")
                response.raise_for_status()
                
                user_data = response.json()
                
                return {
                    'user_id': user_data['user_id'],
                    'username': user_data['username'],
                    'display_name': user_data.get('display_name', user_data['username']),
                    'avatar': user_data.get('avatar')
                }
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError(f"Sleeper username '{username}' not found")
            raise ValueError(f"Failed to authenticate with Sleeper: {e}")
        except Exception as e:
            logger.error(f"Sleeper authentication error: {str(e)}")
            raise ValueError(f"Authentication failed: {str(e)}")
    
    async def get_user_leagues(self, platform_user_id: str) -> List[Dict[str, Any]]:
        """Get all leagues for a user for current season"""
        current_season = datetime.now().year
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/user/{platform_user_id}/leagues/nfl/{current_season}")
                response.raise_for_status()
                
                leagues_data = response.json()
                
                leagues = []
                for league in leagues_data:
                    # Get additional league details
                    league_details = await self.get_league_details(league['league_id'])
                    
                    leagues.append({
                        'league_id': league['league_id'],
                        'name': league['name'],
                        'season': current_season,
                        'team_count': league['total_rosters'],
                        'scoring_type': self._determine_scoring_type(league),
                        'roster_positions': league.get('roster_positions', []),
                        'teams': league_details.get('teams', [])
                    })
                
                return leagues
                
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to get Sleeper leagues for user {platform_user_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error getting Sleeper leagues: {str(e)}")
            return []
    
    async def get_league_details(self, league_id: str) -> Dict[str, Any]:
        """Get detailed league information"""
        try:
            async with httpx.AsyncClient() as client:
                # Get league info
                league_response = await client.get(f"{self.base_url}/league/{league_id}")
                league_response.raise_for_status()
                league_data = league_response.json()
                logger.info(f"League {league_id} status: {league_data.get('status')}")
                
                # Get rosters
                rosters_response = await client.get(f"{self.base_url}/league/{league_id}/rosters")
                rosters_response.raise_for_status()
                rosters_data = rosters_response.json()
                logger.info(f"Found {len(rosters_data)} rosters for league {league_id}")
                
                # Get users (owners)
                users_response = await client.get(f"{self.base_url}/league/{league_id}/users")
                users_response.raise_for_status()
                users_data = users_response.json()
                logger.info(f"Found {len(users_data)} users for league {league_id}")
                
                # Create user lookup
                logger.info(f"Processing {len(users_data)} users for lookup")
                users_lookup = {}
                for user in users_data:
                    if user is None:
                        logger.warning("Found None user in users_data")
                        continue
                    user_id = user.get('user_id')
                    if user_id is None:
                        logger.warning(f"User missing user_id: {user}")
                        continue
                    users_lookup[user_id] = user
                    logger.debug(f"Added user to lookup: {user_id} -> {user.get('username', 'no_username')}")
                
                # Process teams
                teams = []
                logger.info(f"Processing {len(rosters_data)} rosters")
                for i, roster in enumerate(rosters_data):
                    if roster is None:
                        logger.warning(f"Found None roster at index {i}")
                        continue
                    owner_id = roster.get('owner_id')
                    if owner_id is None:
                        logger.warning(f"Roster missing owner_id: {roster}")
                        continue
                    owner = users_lookup.get(owner_id, {})
                    logger.debug(f"Processing roster {i}: owner_id={owner_id}, owner_username={owner.get('username', 'Unknown')}")
                    
                    try:
                        team_data = {
                            'team_id': str(roster['roster_id']),
                            'name': self._get_team_name(roster, owner),
                            'owner_name': owner.get('display_name') or owner.get('username', 'Unknown'),
                            'owner_id': roster['owner_id'],
                            'wins': roster.get('settings', {}).get('wins', 0),
                            'losses': roster.get('settings', {}).get('losses', 0),
                            'ties': roster.get('settings', {}).get('ties', 0),
                            'points_for': float(roster.get('settings', {}).get('fpts', 0)),
                            'points_against': float(roster.get('settings', {}).get('fpts_against', 0)),
                            'waiver_position': roster.get('settings', {}).get('waiver_position'),
                            'roster': roster.get('players', [])
                        }
                    except Exception as team_error:
                        logger.error(f"Error processing team data for roster {i}: {team_error}")
                        logger.error(f"Roster data: {roster}")
                        logger.error(f"Owner data: {owner}")
                        raise
                    teams.append(team_data)
                    logger.debug(f"Processed team: {team_data['name']} (ID: {team_data['team_id']})")
                
                logger.info(f"Successfully processed {len(teams)} teams for league {league_id}")
                
                return {
                    'league_id': league_id,
                    'name': league_data['name'],
                    'season': league_data['season'],
                    'status': league_data['status'],
                    'scoring_settings': league_data.get('scoring_settings', {}),
                    'roster_positions': league_data.get('roster_positions', []),
                    'teams': teams
                }
                
        except Exception as e:
            logger.error(f"Failed to get Sleeper league details for {league_id}: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {}
    
    async def get_league_teams(self, league_id: str) -> List[Dict[str, Any]]:
        """Get all teams in a league"""
        league_details = await self.get_league_details(league_id)
        return league_details.get('teams', [])
    
    async def get_team_roster(self, team_id: str, week: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get team roster for specific week
        Note: Sleeper doesn't directly support roster by team_id, need league context
        This is a simplified version - in practice, you'd need league_id too
        """
        # This would need to be called with league context
        # For now, return empty - this method would be used differently in practice
        logger.warning("get_team_roster called without league context - not fully supported")
        return []
    
    async def get_league_matchups(self, league_id: str, week: int) -> List[Dict[str, Any]]:
        """Get matchups for specific week"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/league/{league_id}/matchups/{week}")
                response.raise_for_status()
                
                matchups_data = response.json()
                
                # Group matchups by matchup_id
                matchups_grouped = {}
                for matchup in matchups_data:
                    matchup_id = matchup.get('matchup_id')
                    if matchup_id not in matchups_grouped:
                        matchups_grouped[matchup_id] = []
                    matchups_grouped[matchup_id].append(matchup)
                
                # Process matchups
                processed_matchups = []
                for matchup_id, teams in matchups_grouped.items():
                    if len(teams) == 2:  # Valid matchup
                        processed_matchups.append({
                            'matchup_id': str(matchup_id),
                            'week': week,
                            'team1_id': str(teams[0]['roster_id']),
                            'team2_id': str(teams[1]['roster_id']),
                            'team1_score': float(teams[0].get('points', 0)),
                            'team2_score': float(teams[1].get('points', 0)),
                            'team1_starters': teams[0].get('starters', []),
                            'team2_starters': teams[1].get('starters', [])
                        })
                
                return processed_matchups
                
        except Exception as e:
            logger.error(f"Failed to get Sleeper matchups for league {league_id}, week {week}: {str(e)}")
            return []
    
    async def get_available_players(self, league_id: str) -> List[Dict[str, Any]]:
        """Get all available (free agent) players"""
        try:
            # Get all players
            players_data = await self._get_all_players()
            
            # Get league rosters to determine taken players
            league_details = await self.get_league_details(league_id)
            taken_players = set()
            
            for team in league_details.get('teams', []):
                roster = team.get('roster', [])
                taken_players.update(roster)
            
            # Filter out taken players
            available_players = []
            for player_id, player_data in players_data.items():
                if player_id not in taken_players:
                    if player_data.get('active', False):  # Only active players
                        available_players.append({
                            'player_id': player_id,
                            'name': f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip(),
                            'position': player_data.get('position'),
                            'team': player_data.get('team'),
                            'age': player_data.get('age'),
                            'experience': player_data.get('years_exp'),
                            'fantasy_positions': player_data.get('fantasy_positions', [])
                        })
            
            return available_players
            
        except Exception as e:
            logger.error(f"Failed to get available players for league {league_id}: {str(e)}")
            return []
    
    async def get_trending_players(self, trend_type: str = "add") -> List[Dict[str, Any]]:
        """Get trending players (add/drop)"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/players/nfl/trending/{trend_type}")
                response.raise_for_status()
                
                trending_data = response.json()
                
                # Get player details
                players_data = await self._get_all_players()
                
                trending_players = []
                for player_entry in trending_data:
                    player_id = player_entry['player_id']
                    count = player_entry['count']
                    
                    if player_id in players_data:
                        player_data = players_data[player_id]
                        trending_players.append({
                            'player_id': player_id,
                            'name': f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip(),
                            'position': player_data.get('position'),
                            'team': player_data.get('team'),
                            'trend_type': trend_type,
                            'trend_count': count,
                            'fantasy_positions': player_data.get('fantasy_positions', [])
                        })
                
                return trending_players
                
        except Exception as e:
            logger.error(f"Failed to get trending players: {str(e)}")
            return []
    
    async def _get_all_players(self) -> Dict[str, Any]:
        """Get all NFL players data with caching"""
        # Check if cache is valid (refresh daily)
        now = datetime.now()
        if (self._players_cache_time and 
            (now - self._players_cache_time).seconds < 86400 and  # 24 hours
            self._players_cache):
            return self._players_cache
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.base_url}/players/nfl")
                response.raise_for_status()
                
                self._players_cache = response.json()
                self._players_cache_time = now
                
                return self._players_cache
                
        except Exception as e:
            logger.error(f"Failed to get all players: {str(e)}")
            return self._players_cache if self._players_cache else {}
    
    def _determine_scoring_type(self, league_data: Dict[str, Any]) -> str:
        """Determine scoring type from league settings"""
        scoring_settings = league_data.get('scoring_settings', {})
        
        # Check for PPR scoring
        rec_points = scoring_settings.get('rec', 0)
        if rec_points >= 1:
            return 'ppr'
        elif rec_points >= 0.5:
            return 'half_ppr'
        else:
            return 'standard'
    
    def _get_team_name(self, roster: Dict[str, Any], owner: Dict[str, Any]) -> str:
        """Get team name, falling back to owner name if no team name"""
        # Sleeper doesn't always have team names, use owner info
        display_name = owner.get('display_name') or owner.get('username', 'Unknown Team')
        
        # Check roster metadata first
        roster_metadata = roster.get('metadata') or {}
        team_name = roster_metadata.get('team_name') if isinstance(roster_metadata, dict) else None
        
        # If no team name in roster, check owner metadata
        if not team_name:
            owner_metadata = owner.get('metadata') or {}
            team_name = owner_metadata.get('team_name') if isinstance(owner_metadata, dict) else None
        
        if team_name:
            return team_name
        else:
            return f"{display_name}'s Team"
    
    async def get_league_transactions(self, league_id: str, week: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get league transactions for specific week or all season"""
        try:
            url = f"{self.base_url}/league/{league_id}/transactions"
            if week:
                url += f"/{week}"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()
                
                transactions_data = response.json()
                
                # Process transactions
                processed_transactions = []
                for transaction in transactions_data:
                    processed_transactions.append({
                        'transaction_id': transaction.get('transaction_id'),
                        'type': transaction.get('type'),
                        'status': transaction.get('status'),
                        'roster_ids': transaction.get('roster_ids', []),
                        'adds': transaction.get('adds', {}),
                        'drops': transaction.get('drops', {}),
                        'waiver_budget': transaction.get('waiver_budget', {}),
                        'created': transaction.get('created'),
                        'week': transaction.get('leg', week)
                    })
                
                return processed_transactions
                
        except Exception as e:
            logger.error(f"Failed to get transactions for league {league_id}: {str(e)}")
            return []