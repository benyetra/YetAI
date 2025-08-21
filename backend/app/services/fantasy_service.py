"""
Fantasy Sports Service - Core fantasy data management and synchronization
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timedelta
import logging
from abc import ABC, abstractmethod

from app.models.fantasy_models import (
    FantasyUser, FantasyLeague, FantasyTeam, FantasyPlayer, 
    FantasyRosterSpot, PlayerProjection, FantasyRecommendation,
    FantasyMatchup, FantasyTransaction, WaiverWireTarget,
    LeagueHistoricalData, CompetitorAnalysis,
    FantasyPlatform, RecommendationType
)
from app.models.database_models import User

logger = logging.getLogger(__name__)

class FantasyPlatformInterface(ABC):
    """Abstract interface for fantasy platform integrations"""
    
    @abstractmethod
    async def authenticate_user(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Authenticate user with platform and return user data"""
        pass
    
    @abstractmethod
    async def get_user_leagues(self, platform_user_id: str) -> List[Dict[str, Any]]:
        """Get all leagues for a user"""
        pass
    
    @abstractmethod
    async def get_league_details(self, league_id: str) -> Dict[str, Any]:
        """Get detailed league information"""
        pass
    
    @abstractmethod
    async def get_league_teams(self, league_id: str) -> List[Dict[str, Any]]:
        """Get all teams in a league"""
        pass
    
    @abstractmethod
    async def get_team_roster(self, team_id: str, week: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get team roster for specific week"""
        pass
    
    @abstractmethod
    async def get_league_matchups(self, league_id: str, week: int) -> List[Dict[str, Any]]:
        """Get matchups for specific week"""
        pass
    
    @abstractmethod
    async def get_available_players(self, league_id: str) -> List[Dict[str, Any]]:
        """Get all available (free agent) players"""
        pass

class FantasyService:
    """Core fantasy sports service for managing fantasy data"""
    
    def __init__(self, db: Session):
        self.db = db
        self.platforms: Dict[FantasyPlatform, FantasyPlatformInterface] = {}
    
    def register_platform(self, platform: FantasyPlatform, interface: FantasyPlatformInterface):
        """Register a platform interface"""
        self.platforms[platform] = interface
        logger.info(f"Registered fantasy platform: {platform}")
    
    async def connect_user_account(self, user_id: int, platform: FantasyPlatform, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Connect a user's fantasy account"""
        try:
            if platform not in self.platforms:
                raise ValueError(f"Platform {platform} not supported")
            
            # Authenticate with platform
            platform_interface = self.platforms[platform]
            auth_data = await platform_interface.authenticate_user(credentials)
            
            # Check if user already connected
            existing_fantasy_user = self.db.query(FantasyUser).filter(
                and_(
                    FantasyUser.user_id == user_id,
                    FantasyUser.platform == platform,
                    FantasyUser.platform_user_id == auth_data['user_id']
                )
            ).first()
            
            if existing_fantasy_user:
                # Update existing connection
                existing_fantasy_user.access_token = auth_data.get('access_token')
                existing_fantasy_user.refresh_token = auth_data.get('refresh_token')
                existing_fantasy_user.token_expires_at = auth_data.get('expires_at')
                existing_fantasy_user.is_active = True
                existing_fantasy_user.sync_error = None
                existing_fantasy_user.updated_at = datetime.utcnow()
                fantasy_user = existing_fantasy_user
            else:
                # Create new connection
                fantasy_user = FantasyUser(
                    user_id=user_id,
                    platform=platform,
                    platform_user_id=auth_data['user_id'],
                    platform_username=auth_data.get('username'),
                    access_token=auth_data.get('access_token'),
                    refresh_token=auth_data.get('refresh_token'),
                    token_expires_at=auth_data.get('expires_at')
                )
                self.db.add(fantasy_user)
            
            self.db.commit()
            
            # Sync leagues immediately after connection
            await self.sync_user_leagues(fantasy_user.id)
            
            return {
                "success": True,
                "fantasy_user_id": fantasy_user.id,
                "platform": platform,
                "username": auth_data.get('username')
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to connect user {user_id} to {platform}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def sync_user_leagues(self, fantasy_user_id: int) -> Dict[str, Any]:
        """Synchronize all leagues for a fantasy user"""
        try:
            fantasy_user = self.db.query(FantasyUser).filter(FantasyUser.id == fantasy_user_id).first()
            if not fantasy_user:
                raise ValueError("Fantasy user not found")
            
            platform_interface = self.platforms[fantasy_user.platform]
            leagues_data = await platform_interface.get_user_leagues(fantasy_user.platform_user_id)
            
            synced_leagues = []
            for league_data in leagues_data:
                league = await self._sync_league(fantasy_user, league_data)
                if league:
                    synced_leagues.append(league)
            
            # Update sync timestamp
            fantasy_user.last_sync = datetime.utcnow()
            fantasy_user.sync_error = None
            self.db.commit()
            
            return {
                "success": True,
                "synced_leagues": len(synced_leagues),
                "leagues": [{"id": l.id, "name": l.name} for l in synced_leagues]
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to sync leagues for fantasy user {fantasy_user_id}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def _sync_league(self, fantasy_user: FantasyUser, league_data: Dict[str, Any]) -> Optional[FantasyLeague]:
        """Sync individual league data"""
        try:
            # Check if league already exists
            existing_league = self.db.query(FantasyLeague).filter(
                and_(
                    FantasyLeague.fantasy_user_id == fantasy_user.id,
                    FantasyLeague.platform_league_id == league_data['league_id']
                )
            ).first()
            
            # Get waiver settings if available
            waiver_settings = league_data.get('waiver_settings', {})
            
            if existing_league:
                # Update existing league
                league = existing_league
                league.name = league_data.get('name', league.name)
                league.team_count = league_data.get('team_count', league.team_count)
                league.scoring_type = league_data.get('scoring_type', league.scoring_type)
                # Update waiver settings
                league.waiver_type = waiver_settings.get('waiver_type', league.waiver_type)
                league.waiver_budget = waiver_settings.get('waiver_budget', league.waiver_budget)
                league.waiver_clear_days = waiver_settings.get('waiver_clear_days', league.waiver_clear_days)
            else:
                # Create new league
                league = FantasyLeague(
                    fantasy_user_id=fantasy_user.id,
                    platform=fantasy_user.platform,
                    platform_league_id=league_data['league_id'],
                    name=league_data['name'],
                    season=league_data.get('season', datetime.now().year),
                    team_count=league_data.get('team_count'),
                    scoring_type=league_data.get('scoring_type'),
                    waiver_type=waiver_settings.get('waiver_type'),
                    waiver_budget=waiver_settings.get('waiver_budget'),
                    waiver_clear_days=waiver_settings.get('waiver_clear_days')
                )
                self.db.add(league)
                self.db.flush()  # Get league ID
            
            # Enable sync for this league (both new and existing)
            league.sync_enabled = True
            league.is_synced = True
            
            # Sync teams
            await self._sync_league_teams(league, league_data.get('teams', []), fantasy_user)
            
            league.last_sync = datetime.utcnow()
            return league
            
        except Exception as e:
            logger.error(f"Failed to sync league {league_data.get('league_id')}: {str(e)}")
            return None
    
    async def _sync_league_teams(self, league: FantasyLeague, teams_data: List[Dict[str, Any]], fantasy_user: FantasyUser):
        """Sync teams for a league"""
        try:
            platform_interface = self.platforms[league.platform]
            
            for team_data in teams_data:
                # Determine if this is the user's team by comparing owner_id with platform_user_id
                is_user_team = team_data.get('owner_id') == fantasy_user.platform_user_id
                
                # Check if team exists
                existing_team = self.db.query(FantasyTeam).filter(
                    and_(
                        FantasyTeam.league_id == league.id,
                        FantasyTeam.platform_team_id == team_data['team_id']
                    )
                ).first()
                
                if existing_team:
                    # Update existing team
                    team = existing_team
                    team.name = team_data.get('name', team.name)
                    team.owner_name = team_data.get('owner_name', team.owner_name)
                    team.is_user_team = is_user_team
                    team.wins = team_data.get('wins', team.wins)
                    team.losses = team_data.get('losses', team.losses)
                    team.points_for = team_data.get('points_for', team.points_for)
                    team.points_against = team_data.get('points_against', team.points_against)
                    team.waiver_position = team_data.get('waiver_position', team.waiver_position)
                else:
                    # Create new team
                    team = FantasyTeam(
                        league_id=league.id,
                        platform_team_id=team_data['team_id'],
                        name=team_data['name'],
                        owner_name=team_data.get('owner_name'),
                        is_user_team=is_user_team,
                        wins=team_data.get('wins', 0),
                        losses=team_data.get('losses', 0),
                        points_for=team_data.get('points_for', 0),
                        points_against=team_data.get('points_against', 0),
                        waiver_position=team_data.get('waiver_position')
                    )
                    self.db.add(team)
                    
        except Exception as e:
            logger.error(f"Failed to sync teams for league {league.id}: {str(e)}")
    
    def get_user_fantasy_accounts(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all fantasy accounts for a user"""
        fantasy_users = self.db.query(FantasyUser).filter(
            and_(FantasyUser.user_id == user_id, FantasyUser.is_active == True)
        ).all()
        
        return [
            {
                "id": fu.id,
                "platform": fu.platform,
                "username": fu.platform_username,
                "last_sync": fu.last_sync,
                "league_count": len(fu.leagues)
            }
            for fu in fantasy_users
        ]
    
    def get_user_leagues(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all leagues for a user across all platforms"""
        leagues = self.db.query(FantasyLeague).join(FantasyUser).filter(
            and_(FantasyUser.user_id == user_id, FantasyLeague.sync_enabled == True)
        ).all()
        
        return [
            {
                "id": league.id,
                "platform_league_id": league.platform_league_id,
                "name": league.name,
                "platform": league.platform,
                "season": league.season,
                "team_count": league.team_count,
                "scoring_type": league.scoring_type,
                "last_sync": league.last_sync,
                "waiver_type": league.waiver_type,
                "waiver_budget": league.waiver_budget,
                "user_team": self._get_user_team(league)
            }
            for league in leagues
        ]
    
    def _get_user_team(self, league: FantasyLeague) -> Optional[Dict[str, Any]]:
        """Get user's team in a league"""
        user_team = self.db.query(FantasyTeam).filter(
            and_(
                FantasyTeam.league_id == league.id,
                FantasyTeam.is_user_team == True
            )
        ).first()
        
        if user_team:
            return {
                "id": user_team.id,
                "name": user_team.name,
                "wins": user_team.wins,
                "losses": user_team.losses,
                "points_for": user_team.points_for,
                "waiver_position": user_team.waiver_position
            }
        return None
    
    async def generate_start_sit_recommendations(self, user_id: int, week: int) -> List[Dict[str, Any]]:
        """Generate start/sit recommendations for user's teams"""
        recommendations = []
        user_leagues = self.get_user_leagues(user_id)
        
        for league_data in user_leagues:
            league_id = league_data["id"]
            league = self.db.query(FantasyLeague).filter(FantasyLeague.id == league_id).first()
            user_team = league_data.get("user_team")
            
            if not user_team or not league:
                continue
            
            try:
                # Get platform interface for roster data
                platform_interface = self.platforms.get(league.platform)
                if not platform_interface:
                    continue
                
                # Get current roster from platform
                roster_data = await platform_interface.get_team_roster(user_team["id"], week)
                
                # Generate recommendations for each roster position
                league_recommendations = await self._generate_start_sit_for_league(
                    league_id, league_data["name"], roster_data, week
                )
                
                recommendations.extend(league_recommendations)
                
            except Exception as e:
                logger.error(f"Failed to generate start/sit recommendations for league {league_id}: {str(e)}")
                continue
        
        # Sort by confidence and projected impact
        recommendations.sort(key=lambda x: (x.get("confidence", 0), x.get("projected_points", 0)), reverse=True)
        return recommendations[:15]  # Return top 15 recommendations
    
    async def _generate_start_sit_for_league(self, league_id: int, league_name: str, 
                                           roster_data: List[Dict], week: int) -> List[Dict[str, Any]]:
        """Generate start/sit recommendations for a specific league"""
        recommendations = []
        
        # Group players by position for comparison
        position_groups = {}
        for player_data in roster_data:
            position = player_data.get("position", "UNKNOWN")
            if position not in position_groups:
                position_groups[position] = []
            position_groups[position].append(player_data)
        
        # Generate recommendations for each position group
        for position, players in position_groups.items():
            if position in ["BENCH", "IR", "UNKNOWN"]:
                continue
                
            # Sort players by projected performance
            sorted_players = await self._rank_players_by_performance(players, week)
            
            # Generate start/sit advice based on rankings and typical position slots
            position_recommendations = self._create_position_recommendations(
                league_id, league_name, position, sorted_players, week
            )
            
            recommendations.extend(position_recommendations)
        
        return recommendations
    
    async def _rank_players_by_performance(self, players: List[Dict], week: int) -> List[Dict]:
        """Rank players by expected performance this week"""
        for player in players:
            # Check for existing projections first
            projection = self.db.query(PlayerProjection).filter(
                and_(
                    PlayerProjection.player_id == player.get("player_id"),
                    PlayerProjection.week == week
                )
            ).first()
            
            if projection:
                player["projected_points"] = projection.projected_points
                player["confidence"] = projection.confidence
                player["reasoning"] = projection.reasoning
            else:
                # Generate basic projections based on available data
                player.update(self._generate_basic_projection(player, week))
        
        # Sort by projected points
        return sorted(players, key=lambda p: p.get("projected_points", 0), reverse=True)
    
    def _generate_basic_projection(self, player: Dict, week: int) -> Dict:
        """Generate basic projection when detailed data isn't available"""
        position = player.get("position", "")
        player_name = player.get("name", "Unknown Player")
        
        # Position-based baseline projections
        baseline_projections = {
            "QB": {"points": 18, "floor": 12, "ceiling": 28},
            "RB": {"points": 12, "floor": 6, "ceiling": 22},
            "WR": {"points": 11, "floor": 5, "ceiling": 25},
            "TE": {"points": 8, "floor": 3, "ceiling": 18},
            "K": {"points": 7, "floor": 2, "ceiling": 15},
            "DEF": {"points": 8, "floor": 0, "ceiling": 20}
        }
        
        baseline = baseline_projections.get(position, {"points": 8, "floor": 0, "ceiling": 15})
        
        # Add some variance based on player tier (this could be enhanced with real data)
        import random
        variance = random.uniform(-0.2, 0.2)  # ±20% variance
        projected_points = max(baseline["floor"], baseline["points"] * (1 + variance))
        
        return {
            "projected_points": round(projected_points, 1),
            "confidence": 65,  # Medium confidence for basic projections
            "reasoning": f"Week {week} projection based on position average"
        }
    
    def _create_position_recommendations(self, league_id: int, league_name: str, 
                                       position: str, sorted_players: List[Dict], 
                                       week: int) -> List[Dict[str, Any]]:
        """Create start/sit recommendations for a position group"""
        recommendations = []
        
        # Define typical starting slots per position
        typical_starters = {
            "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1
        }
        
        starting_slots = typical_starters.get(position, 1)
        
        for i, player in enumerate(sorted_players):
            is_starter = i < starting_slots
            recommendation_type = "START" if is_starter else "SIT"
            
            # Determine confidence and reasoning
            projected_points = player.get("projected_points", 0)
            confidence = player.get("confidence", 50)
            
            # Create reasoning based on ranking and projections
            if is_starter:
                if i == 0:
                    reasoning = f"Top {position} on your roster this week"
                else:
                    reasoning = f"Solid {position} option, ranked #{i+1} on your team"
            else:
                if projected_points < 5:
                    reasoning = f"Low projection ({projected_points} pts), consider benching"
                else:
                    reasoning = f"Bench option, ranked #{i+1} at {position}"
            
            # Add matchup context if available
            if player.get("opponent"):
                reasoning += f" vs {player['opponent']}"
            
            recommendation = {
                "league_id": league_id,
                "league_name": league_name,
                "player_id": player.get("player_id"),
                "player_name": player.get("name", "Unknown"),
                "position": position,
                "team": player.get("team", "FA"),
                "recommendation": recommendation_type,
                "projected_points": projected_points,
                "confidence": confidence,
                "reasoning": reasoning,
                "rank_in_position": i + 1,
                "total_in_position": len(sorted_players),
                "week": week,
                "is_questionable": player.get("injury_status") in ["Q", "D"],
                "opponent": player.get("opponent")
            }
            
            # Only include recommendations with meaningful advice
            if (recommendation_type == "START" and projected_points >= 8) or \
               (recommendation_type == "SIT" and projected_points < 12):
                recommendations.append(recommendation)
        
        return recommendations
    
    
    def disconnect_fantasy_account(self, user_id: int, fantasy_user_id: int) -> Dict[str, Any]:
        """Disconnect a fantasy account"""
        try:
            fantasy_user = self.db.query(FantasyUser).filter(
                and_(
                    FantasyUser.id == fantasy_user_id,
                    FantasyUser.user_id == user_id
                )
            ).first()
            
            if not fantasy_user:
                return {"success": False, "error": "Fantasy account not found"}
            
            # Deactivate instead of deleting to preserve historical data
            fantasy_user.is_active = False
            fantasy_user.access_token = None
            fantasy_user.refresh_token = None
            
            # Disable sync for all leagues
            for league in fantasy_user.leagues:
                league.sync_enabled = False
            
            self.db.commit()
            
            return {"success": True, "message": "Fantasy account disconnected"}
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to disconnect fantasy account {fantasy_user_id}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def disconnect_league(self, user_id: int, league_id: int) -> Dict[str, Any]:
        """Disconnect and completely remove a specific league and all its data"""
        try:
            # Verify the league belongs to the user
            league = self.db.query(FantasyLeague).join(FantasyUser).filter(
                and_(
                    FantasyLeague.id == league_id,
                    FantasyUser.user_id == user_id
                )
            ).first()
            
            if not league:
                return {"success": False, "error": "League not found or doesn't belong to user"}
            
            league_name = league.name
            
            # Delete all related data in correct order (children first)
            # 1. Fantasy recommendations
            self.db.query(FantasyRecommendation).filter(FantasyRecommendation.league_id == league_id).delete()
            
            # 2. Waiver wire targets
            self.db.query(WaiverWireTarget).filter(WaiverWireTarget.league_id == league_id).delete()
            
            # 3. Fantasy matchups
            self.db.query(FantasyMatchup).filter(FantasyMatchup.league_id == league_id).delete()
            
            # 4. Fantasy transactions
            self.db.query(FantasyTransaction).filter(FantasyTransaction.league_id == league_id).delete()
            
            # 5. League historical data
            self.db.query(LeagueHistoricalData).filter(LeagueHistoricalData.league_id == league_id).delete()
            
            # 6. Competitor analysis
            self.db.query(CompetitorAnalysis).filter(CompetitorAnalysis.league_id == league_id).delete()
            
            # 7. Fantasy teams and roster spots
            teams = self.db.query(FantasyTeam).filter(FantasyTeam.league_id == league_id).all()
            for team in teams:
                # Delete roster spots first
                self.db.query(FantasyRosterSpot).filter(FantasyRosterSpot.team_id == team.id).delete()
            # Delete teams
            self.db.query(FantasyTeam).filter(FantasyTeam.league_id == league_id).delete()
            
            # 8. Finally delete the league itself
            self.db.delete(league)
            
            self.db.commit()
            
            logger.info(f"Successfully disconnected and removed league '{league_name}' (ID: {league_id}) for user {user_id}")
            return {
                "success": True, 
                "message": f"League '{league_name}' has been completely removed from your account"
            }
        
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error disconnecting league {league_id}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def get_league_standings(self, league_id: int) -> List[Dict[str, Any]]:
        """Get league standings with team records and stats"""
        try:
            # Get all teams in the league
            teams = self.db.query(FantasyTeam).filter(FantasyTeam.league_id == league_id).all()
            
            standings = []
            for team in teams:
                # Calculate additional stats
                total_games = team.wins + team.losses
                win_percentage = team.wins / total_games if total_games > 0 else 0
                points_per_game = team.points_for / total_games if total_games > 0 else 0
                points_against_per_game = team.points_against / total_games if total_games > 0 else 0
                
                team_data = {
                    "team_id": team.id,
                    "platform_team_id": team.platform_team_id,
                    "name": team.name,
                    "owner_name": team.owner_name,
                    "is_user_team": team.is_user_team,
                    "wins": team.wins,
                    "losses": team.losses,
                    "ties": getattr(team, 'ties', 0),
                    "win_percentage": round(win_percentage, 3),
                    "points_for": float(team.points_for) if team.points_for else 0,
                    "points_against": float(team.points_against) if team.points_against else 0,
                    "points_per_game": round(points_per_game, 2),
                    "points_against_per_game": round(points_against_per_game, 2),
                    "point_differential": float(team.points_for - team.points_against) if team.points_for and team.points_against else 0,
                    "waiver_position": team.waiver_position
                }
                standings.append(team_data)
            
            # Sort by wins (descending), then by points_for (descending)
            standings.sort(key=lambda x: (-x["wins"], -x["points_for"]))
            
            # Add rank
            for i, team in enumerate(standings):
                team["rank"] = i + 1
            
            return standings
            
        except Exception as e:
            logger.error(f"Failed to get league standings for league {league_id}: {str(e)}")
            return []
    
    async def get_league_matchups(self, league_id: int, week: int) -> List[Dict[str, Any]]:
        """Get league matchups for a specific week"""
        try:
            # Get the league to determine platform
            league = self.db.query(FantasyLeague).filter(FantasyLeague.id == league_id).first()
            if not league:
                raise ValueError(f"League {league_id} not found")
            
            # Get platform interface
            platform_interface = self.platforms.get(league.platform)
            if not platform_interface:
                raise ValueError(f"Platform {league.platform} not supported")
            
            # Get matchups from platform API
            matchups_data = await platform_interface.get_league_matchups(league.platform_league_id, week)
            
            # Get teams for lookup
            teams = self.db.query(FantasyTeam).filter(FantasyTeam.league_id == league_id).all()
            teams_lookup = {team.platform_team_id: team for team in teams}
            
            # Process matchups
            processed_matchups = []
            for matchup in matchups_data:
                team1_id = matchup.get('team1_id')
                team2_id = matchup.get('team2_id')
                
                team1 = teams_lookup.get(team1_id)
                team2 = teams_lookup.get(team2_id)
                
                if team1 and team2:
                    processed_matchup = {
                        "matchup_id": matchup.get('matchup_id'),
                        "week": week,
                        "team1": {
                            "id": team1.id,
                            "name": team1.name,
                            "owner_name": team1.owner_name,
                            "is_user_team": team1.is_user_team,
                            "score": float(matchup.get('team1_score', 0)),
                            "starters": matchup.get('team1_starters', [])
                        },
                        "team2": {
                            "id": team2.id,
                            "name": team2.name,
                            "owner_name": team2.owner_name,
                            "is_user_team": team2.is_user_team,
                            "score": float(matchup.get('team2_score', 0)),
                            "starters": matchup.get('team2_starters', [])
                        },
                        "status": self._determine_matchup_status(matchup.get('team1_score', 0), matchup.get('team2_score', 0)),
                        "user_involved": team1.is_user_team or team2.is_user_team
                    }
                    processed_matchups.append(processed_matchup)
            
            # Sort user matchups first
            processed_matchups.sort(key=lambda x: (not x["user_involved"], x["matchup_id"]))
            
            return processed_matchups
            
        except Exception as e:
            logger.error(f"Failed to get league matchups for league {league_id}, week {week}: {str(e)}")
            return []
    
    def _determine_matchup_status(self, score1: float, score2: float) -> str:
        """Determine matchup status based on scores"""
        if score1 == 0 and score2 == 0:
            return "upcoming"
        elif score1 > 0 or score2 > 0:
            if score1 == score2:
                return "tied"
            else:
                return "completed"
        return "upcoming"
    
    # ============================================================================
    # ENHANCED AI RECOMMENDATION METHODS WITH LEAGUE CONTEXT
    # ============================================================================
    
    async def generate_start_sit_recommendations(self, user_id: int, week: int) -> List[Dict[str, Any]]:
        """Generate enhanced start/sit recommendations with league context"""
        recommendations = []
        user_leagues = self.get_user_leagues(user_id)
        
        for league_data in user_leagues:
            league_id = league_data["id"]
            league = self.db.query(FantasyLeague).filter(FantasyLeague.id == league_id).first()
            
            if not league:
                continue
            
            try:
                # Get league rules for context-aware recommendations
                league_rules = await self._get_league_rules_context(league_data)
                
                # Get user's team roster
                user_team = league_data.get("user_team")
                if not user_team:
                    continue
                
                # Get roster data for this league
                platform_interface = self.platforms.get(league.platform)
                if not platform_interface:
                    continue
                
                roster_data = await platform_interface.get_team_roster(
                    user_team["platform_team_id"], week
                )
                
                # Generate recommendations for each position group
                position_groups = self._group_players_by_position(roster_data)
                
                for position, players in position_groups.items():
                    if not players:
                        continue
                    
                    # Get enhanced projections using league context
                    players_with_projections = []
                    for player in players:
                        projection = self._get_enhanced_player_projection(
                            player, week, league_rules
                        )
                        player_data = {**player, **projection}
                        players_with_projections.append(player_data)
                    
                    # Sort by league-adjusted projected points
                    sorted_players = sorted(
                        players_with_projections, 
                        key=lambda x: x.get("league_adjusted_points", 0), 
                        reverse=True
                    )
                    
                    # Create enhanced start/sit recommendations
                    position_recommendations = self._create_enhanced_position_recommendations(
                        league_id, league_data["name"], position, sorted_players, week, league_rules
                    )
                    recommendations.extend(position_recommendations)
                    
            except Exception as e:
                logger.error(f"Failed to generate start/sit for league {league_id}: {str(e)}")
                continue
        
        return recommendations
    
    async def _detect_superflex_league(self, league_id: int) -> Dict[str, Any]:
        """Detect if league has superflex or 2QB configuration"""
        try:
            # Check roster positions to detect superflex/2QB leagues
            # Look at roster spots to see position distribution
            roster_positions = self.db.query(FantasyRosterSpot.position).filter(
                FantasyRosterSpot.team_id.in_(
                    self.db.query(FantasyTeam.id).filter(FantasyTeam.league_id == league_id)
                )
            ).distinct().all()
            
            positions_list = [pos[0] for pos in roster_positions]
            
            # Count QB and SUPERFLEX positions
            qb_slots = positions_list.count('QB')
            superflex_slots = positions_list.count('SUPER_FLEX') + positions_list.count('SUPERFLEX')
            
            # Determine if this is a superflex or 2QB league
            has_superflex = superflex_slots > 0
            is_2qb = qb_slots >= 2
            
            # Calculate QB premium multiplier based on league type
            if has_superflex:
                # Superflex leagues: QB can be played in FLEX, significant premium
                superflex_multiplier = 1.4
            elif is_2qb:
                # 2QB leagues: Must start 2 QBs, extreme premium
                superflex_multiplier = 1.6
            else:
                # Standard 1QB leagues: No premium
                superflex_multiplier = 1.0
            
            return {
                "has_superflex": has_superflex,
                "is_2qb": is_2qb,
                "qb_slots": max(qb_slots, 1),  # At least 1 QB slot
                "superflex_slots": superflex_slots,
                "superflex_multiplier": superflex_multiplier,
                "league_type": "superflex" if has_superflex else ("2qb" if is_2qb else "standard")
            }
            
        except Exception as e:
            logger.error(f"Failed to detect superflex configuration for league {league_id}: {str(e)}")
            # Default to standard 1QB league
            return {
                "has_superflex": False,
                "is_2qb": False,
                "qb_slots": 1,
                "superflex_slots": 0,
                "superflex_multiplier": 1.0,
                "league_type": "standard"
            }
    
    async def _get_league_rules_context(self, league_data: Dict[str, Any]) -> Dict[str, Any]:
        """Get league rules context for enhanced recommendations"""
        scoring_type = league_data.get("scoring_type", "standard")
        league_id = league_data["id"]
        
        # PPR analysis
        ppr_value = 0
        if scoring_type == "ppr":
            ppr_value = 1.0
        elif scoring_type == "half_ppr":
            ppr_value = 0.5
        
        # Detect superflex/2QB league configuration
        superflex_info = await self._detect_superflex_league(league_id)
        
        return {
            "league_id": league_id,
            "league_name": league_data["name"],
            "scoring_type": scoring_type,
            "ppr_value": ppr_value,
            "team_count": league_data.get("team_count", 12),
            "superflex_config": superflex_info,
            "ai_context": {
                "prioritize_volume": ppr_value > 0,  # PPR leagues favor target volume
                "rb_premium": ppr_value < 0.5,  # Standard/half-PPR favors RBs more
                "wr_target_bonus": ppr_value,  # Direct PPR bonus for WR targets
                "qb_premium": superflex_info["has_superflex"] or superflex_info["qb_slots"] >= 2,  # QB premium in superflex/2QB
                "superflex_multiplier": superflex_info["superflex_multiplier"],  # QB value multiplier
                "position_scarcity": {
                    "qb": superflex_info["qb_slots"], 
                    "rb": 2, 
                    "wr": 2, 
                    "te": 1, 
                    "flex": 1,
                    "superflex": superflex_info["superflex_slots"]
                }
            }
        }
    
    def _get_enhanced_player_projection(self, player: Dict, week: int, league_rules: Dict) -> Dict[str, Any]:
        """Get enhanced projections that factor in league scoring rules"""
        position = player.get("position", "")
        
        # Base projections by position
        base_projections = {
            "QB": {"points": 18, "floor": 12, "ceiling": 28},
            "RB": {"points": 12, "floor": 6, "ceiling": 22},
            "WR": {"points": 11, "floor": 5, "ceiling": 25},
            "TE": {"points": 8, "floor": 3, "ceiling": 18},
            "K": {"points": 7, "floor": 2, "ceiling": 15},
            "DEF": {"points": 8, "floor": 0, "ceiling": 20}
        }
        
        baseline = base_projections.get(position, {"points": 8, "floor": 0, "ceiling": 15})
        base_points = baseline["points"]
        
        # League-specific adjustments
        ppr_value = league_rules["ppr_value"]
        ai_context = league_rules["ai_context"]
        
        # PPR adjustments for skill positions
        league_adjusted_points = base_points
        reasoning_factors = []
        
        if position == "WR" and ppr_value > 0:
            # WRs get bonus in PPR leagues (assume ~6 targets/game)
            ppr_bonus = 6 * ppr_value
            league_adjusted_points += ppr_bonus
            reasoning_factors.append(f"+{ppr_bonus:.1f} PPR bonus")
        
        elif position == "RB" and ppr_value < 0.5:
            # RBs get slight premium in standard leagues
            rb_premium = base_points * 0.1
            league_adjusted_points += rb_premium
            reasoning_factors.append(f"+{rb_premium:.1f} standard league RB bonus")
        
        elif position == "TE" and ppr_value > 0:
            # TEs get moderate PPR bonus (assume ~4 targets/game)
            ppr_bonus = 4 * ppr_value
            league_adjusted_points += ppr_bonus
            reasoning_factors.append(f"+{ppr_bonus:.1f} PPR bonus")
        
        elif position == "QB" and ai_context["qb_premium"]:
            # Enhanced quarterback valuation for superflex/2QB leagues
            superflex_multiplier = ai_context["superflex_multiplier"]
            superflex_config = league_rules["superflex_config"]
            
            if superflex_config["has_superflex"]:
                # Superflex leagues: QB becomes highly valuable flexible option
                qb_premium = base_points * (superflex_multiplier - 1.0)
                league_adjusted_points += qb_premium
                reasoning_factors.append(f"+{qb_premium:.1f} superflex QB premium")
                
                # Additional bonus for top-tier QBs in superflex
                if base_points >= 20:  # Top-tier QB threshold
                    elite_bonus = 2.0
                    league_adjusted_points += elite_bonus
                    reasoning_factors.append(f"+{elite_bonus} elite QB superflex bonus")
                    
            elif superflex_config["is_2qb"]:
                # 2QB leagues: Extreme QB scarcity, massive premium
                qb_premium = base_points * (superflex_multiplier - 1.0)
                league_adjusted_points += qb_premium
                reasoning_factors.append(f"+{qb_premium:.1f} 2QB league premium")
                
                # Even backup QBs become very valuable in 2QB
                if base_points >= 15:  # Any startable QB
                    scarcity_bonus = 3.0
                    league_adjusted_points += scarcity_bonus
                    reasoning_factors.append(f"+{scarcity_bonus} 2QB scarcity bonus")
        
        # Position scarcity adjustments
        team_count = league_rules["team_count"]
        if position == "TE" and team_count >= 12:
            # TE premium in larger leagues
            scarcity_bonus = 1.5
            league_adjusted_points += scarcity_bonus
            reasoning_factors.append(f"+{scarcity_bonus} TE scarcity")
        
        elif position == "QB" and team_count >= 14 and ai_context["qb_premium"]:
            # Additional QB scarcity in large superflex/2QB leagues
            large_league_bonus = 1.0
            league_adjusted_points += large_league_bonus
            reasoning_factors.append(f"+{large_league_bonus} large league QB scarcity")
        
        # Calculate confidence based on league context
        confidence = 65  # Base confidence
        if ai_context["prioritize_volume"] and position in ["WR", "RB"]:
            confidence += 10  # Higher confidence in PPR for volume players
        
        if position == "QB" and ai_context["qb_premium"]:
            # Higher confidence for QB recommendations in superflex/2QB leagues
            if ai_context["superflex_multiplier"] >= 1.4:
                confidence += 15  # Very confident in QB value in superflex/2QB
            else:
                confidence += 5   # Moderately confident in standard leagues
        
        # Create enhanced reasoning
        base_reason = f"Week {week} projection for {league_rules['scoring_type'].replace('_', ' ').title()} league"
        if reasoning_factors:
            base_reason += f" ({', '.join(reasoning_factors)})"
        
        return {
            "projected_points": round(base_points, 1),
            "league_adjusted_points": round(league_adjusted_points, 1),
            "confidence": min(confidence, 95),
            "reasoning": base_reason,
            "league_context": {
                "scoring_type": league_rules["scoring_type"],
                "ppr_value": ppr_value,
                "adjustments": reasoning_factors
            }
        }
    
    def _group_players_by_position(self, roster_data: List[Dict]) -> Dict[str, List[Dict]]:
        """Group roster players by position"""
        position_groups = {}
        for player in roster_data:
            position = player.get("position", "UNKNOWN")
            if position not in position_groups:
                position_groups[position] = []
            position_groups[position].append(player)
        return position_groups
    
    def _create_enhanced_position_recommendations(self, league_id: int, league_name: str, 
                                               position: str, sorted_players: List[Dict], 
                                               week: int, league_rules: Dict) -> List[Dict[str, Any]]:
        """Create enhanced start/sit recommendations with league context"""
        recommendations = []
        
        # Position-specific starting slots based on league rules
        position_slots = league_rules["ai_context"]["position_scarcity"]
        starting_slots = position_slots.get(position.lower(), 1)
        
        # Adjust for FLEX considerations
        if position in ["RB", "WR", "TE"]:
            starting_slots += position_slots.get("flex", 1)  # Account for FLEX slot
        
        for i, player in enumerate(sorted_players):
            is_starter = i < starting_slots
            recommendation_type = "START" if is_starter else "SIT"
            
            # Get projection data
            league_adjusted_points = player.get("league_adjusted_points", 0)
            confidence = player.get("confidence", 50)
            base_reasoning = player.get("reasoning", "")
            
            # Enhanced reasoning with league context
            if is_starter:
                if i == 0:
                    reasoning = f"Top {position} option in {league_rules['scoring_type'].replace('_', ' ')} league"
                else:
                    reasoning = f"Strong {position} play, ranked #{i+1} for {league_rules['scoring_type'].replace('_', ' ')} scoring"
            else:
                reasoning = f"Bench option in {league_rules['scoring_type'].replace('_', ' ')} league, consider as FLEX if stronger than other positions"
            
            # Add league-specific context
            if league_rules["ppr_value"] > 0 and position in ["WR", "TE"]:
                reasoning += f" (benefits from {league_rules['ppr_value']} PPR)"
            elif league_rules["ai_context"]["rb_premium"] and position == "RB":
                reasoning += " (RB premium in standard scoring)"
            elif position == "QB" and league_rules["ai_context"]["qb_premium"]:
                superflex_config = league_rules["superflex_config"]
                if superflex_config["has_superflex"]:
                    reasoning += " (high value in superflex league)"
                elif superflex_config["is_2qb"]:
                    reasoning += " (critical in 2QB league)"
            
            recommendation = {
                "league_id": league_id,
                "league_name": league_name,
                "player_id": player.get("player_id"),
                "player_name": player.get("name", "Unknown"),
                "position": position,
                "team": player.get("team", "FA"),
                "recommendation": recommendation_type,
                "projected_points": player.get("projected_points", 0),
                "league_adjusted_points": league_adjusted_points,
                "confidence": confidence,
                "reasoning": reasoning,
                "rank_in_position": i + 1,
                "total_in_position": len(sorted_players),
                "week": week,
                "is_questionable": player.get("injury_status") in ["Q", "D"],
                "opponent": player.get("opponent"),
                "league_context": player.get("league_context", {}),
                "scoring_type": league_rules["scoring_type"]
            }
            
            # Include recommendations with meaningful differences
            if (recommendation_type == "START" and league_adjusted_points >= 8) or \
               (recommendation_type == "SIT" and league_adjusted_points < 15):
                recommendations.append(recommendation)
        
        return recommendations
    
    # Enhanced Waiver Wire Recommendations
    async def generate_waiver_wire_recommendations(self, user_id: int, week: int) -> List[Dict[str, Any]]:
        """Generate enhanced waiver wire recommendations with league context and FAAB suggestions"""
        recommendations = []
        user_leagues = self.get_user_leagues(user_id)
        
        for league_data in user_leagues:
            league_id = league_data["id"]
            league = self.db.query(FantasyLeague).filter(FantasyLeague.id == league_id).first()
            
            if not league:
                continue
            
            try:
                # Get league rules for context-aware recommendations
                league_rules = await self._get_league_rules_context(league_data)
                
                # Get platform interface
                platform_interface = self.platforms.get(league.platform)
                if not platform_interface:
                    continue
                
                # Get trending players and available players
                trending_adds = await platform_interface.get_trending_players("add")
                available_players = await platform_interface.get_available_players(league.platform_league_id)
                
                # Get user's team to identify roster needs
                user_team = league_data.get("user_team")
                if not user_team:
                    continue
                
                # Enhanced roster needs analysis with league context
                roster_needs = await self._analyze_enhanced_roster_needs(
                    league_id, user_team["id"], league_rules
                )
                
                # Generate enhanced recommendations
                league_recommendations = self._generate_enhanced_league_recommendations(
                    league_id, league_data["name"], trending_adds, available_players, 
                    roster_needs, league_rules
                )
                
                recommendations.extend(league_recommendations)
                
            except Exception as e:
                logger.error(f"Failed to generate waiver recommendations for league {league_id}: {str(e)}")
                continue
        
        # Sort by priority score and return top recommendations
        recommendations.sort(key=lambda x: x["priority_score"], reverse=True)
        return recommendations[:20]  # Return top 20 recommendations
    
    async def _analyze_enhanced_roster_needs(self, league_id: int, team_id: int, 
                                           league_rules: Dict[str, Any]) -> Dict[str, int]:
        """Enhanced roster needs analysis with league context"""
        try:
            # Get current roster spots
            roster_spots = self.db.query(FantasyRosterSpot).filter(
                FantasyRosterSpot.team_id == team_id
            ).all()
            
            # Count players by position
            position_counts = {}
            for spot in roster_spots:
                if spot.player and spot.position != "BENCH":
                    pos = spot.player.position
                    position_counts[pos] = position_counts.get(pos, 0) + 1
            
            # League-specific position needs based on rules
            position_slots = league_rules["ai_context"]["position_scarcity"]
            
            # Calculate enhanced position needs
            position_needs = {}
            for pos, typical_count in position_slots.items():
                if pos == "flex":  # Skip flex as it's covered by RB/WR/TE
                    continue
                    
                current_count = position_counts.get(pos.upper(), 0)
                need_score = max(0, typical_count - current_count) * 2
                
                # League-specific adjustments
                if pos == "wr" and league_rules["ai_context"]["prioritize_volume"]:
                    need_score += 1  # Extra WR need in PPR leagues
                elif pos == "rb" and league_rules["ai_context"]["rb_premium"]:
                    need_score += 1  # Extra RB need in standard leagues
                elif pos == "te" and league_rules["team_count"] >= 12:
                    need_score += 1  # TE premium in larger leagues
                
                # Add bonus for thin positions
                if current_count <= 1:
                    need_score += 1
                
                position_needs[pos.upper()] = need_score
            
            return position_needs
            
        except Exception as e:
            logger.error(f"Failed to analyze enhanced roster needs: {str(e)}")
            return {}
    
    def _generate_enhanced_league_recommendations(self, league_id: int, league_name: str, 
                                                trending_adds: List[Dict], available_players: List[Dict],
                                                roster_needs: Dict[str, int], league_rules: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate enhanced recommendations with league context and FAAB suggestions"""
        recommendations = []
        
        # Create lookup for available players
        available_lookup = {p.get("player_id"): p for p in available_players}
        
        for trending_player in trending_adds[:15]:  # Top 15 trending adds
            player_id = trending_player.get("player_id")
            
            # Check if player is available in this league
            if player_id not in available_lookup:
                continue
            
            player = available_lookup[player_id]
            position = player.get("position", "")
            
            # Calculate enhanced priority score with league context
            priority_score = self._calculate_enhanced_priority_score(
                trending_player, player, roster_needs, league_rules
            )
            
            if priority_score > 0:
                # Generate appropriate waiver suggestions based on league type
                waiver_suggestion = self._generate_waiver_suggestion(priority_score, league_rules, player)
                
                recommendation = {
                    "league_id": league_id,
                    "league_name": league_name,
                    "player_id": player_id,
                    "player_name": player.get("name", ""),
                    "position": position,
                    "team": player.get("team", "FA"),
                    "priority_score": priority_score,
                    "trend_count": trending_player.get("trend_count", 0),
                    "reason": self._generate_enhanced_recommendation_reason(
                        player, roster_needs, trending_player, league_rules
                    ),
                    "waiver_suggestion": waiver_suggestion,
                    "league_context": {
                        "scoring_type": league_rules["scoring_type"],
                        "ppr_value": league_rules["ppr_value"],
                        "position_value": self._get_position_value_in_league(position, league_rules)
                    },
                    "age": player.get("age"),
                    "experience": player.get("experience"),
                    "fantasy_positions": player.get("fantasy_positions", [])
                }
                recommendations.append(recommendation)
        
        return recommendations
    
    def _calculate_enhanced_priority_score(self, trending_player: Dict, player: Dict, 
                                         roster_needs: Dict[str, int], league_rules: Dict[str, Any]) -> float:
        """Calculate enhanced priority score with league context"""
        score = 0.0
        position = player.get("position", "")
        
        # Base score from trending count
        trend_count = trending_player.get("trend_count", 0)
        score += min(trend_count / 10, 5.0)  # Max 5 points from trending
        
        # Position need bonus with league context
        position_need = roster_needs.get(position, 0)
        score += position_need * 2  # Up to 6 points for high need positions
        
        # League-specific bonuses
        ppr_value = league_rules["ppr_value"]
        ai_context = league_rules["ai_context"]
        
        if position == "WR" and ppr_value > 0:
            score += ppr_value * 2  # WR bonus in PPR leagues
        elif position == "RB" and ppr_value < 0.5:
            score += 1.5  # RB bonus in standard leagues
        elif position == "TE" and league_rules["team_count"] >= 12:
            score += 2.0  # TE premium in larger leagues
        elif position == "QB" and ai_context["qb_premium"]:
            # Enhanced QB valuation for superflex/2QB leagues
            superflex_config = league_rules["superflex_config"]
            if superflex_config["has_superflex"]:
                score += 4.0  # High value QB addition in superflex
            elif superflex_config["is_2qb"]:
                score += 6.0  # Critical QB addition in 2QB leagues
            
            # Additional bonus for backup QBs in these formats
            if position_need >= 2:  # Need depth at QB
                score += 2.0
        
        # Young player bonus (higher upside)
        age = player.get("age")
        if age and age < 26:
            score += 1.0
        
        # Experience factor
        experience = player.get("experience")
        if experience and 2 <= experience <= 5:
            score += 0.5  # Sweet spot years
        
        return round(score, 2)
    
    def _generate_waiver_suggestion(self, priority_score: float, league_rules: Dict[str, Any], player: Dict[str, Any]) -> Dict[str, Any]:
        """Generate waiver suggestions based on league type (FAAB vs waiver priority)"""
        league_id = league_rules["league_id"]
        
        # Check if this is a FAAB league - be defensive and default to waiver priority
        league = self.db.query(FantasyLeague).filter(FantasyLeague.id == league_id).first()
        
        # Only use FAAB if explicitly set to 'FAAB' and has a budget
        is_faab_league = (league and 
                         league.waiver_type == 'FAAB' and 
                         league.waiver_budget and 
                         league.waiver_budget > 0)
        
        if is_faab_league:
            return self._generate_faab_suggestion(priority_score, league_rules, league.waiver_budget)
        else:
            return self._generate_waiver_priority_suggestion(priority_score, league_rules, player)
    
    def _generate_faab_suggestion(self, priority_score: float, league_rules: Dict[str, Any], waiver_budget: int) -> Dict[str, Any]:
        """Generate FAAB bidding suggestions for FAAB leagues"""
        # Base FAAB percentage based on priority score
        if priority_score >= 8:
            base_percentage = 20  # High priority
            tier = "Must-have"
        elif priority_score >= 6:
            base_percentage = 12  # Medium-high priority
            tier = "Strong Add"
        elif priority_score >= 4:
            base_percentage = 6   # Medium priority
            tier = "Good Add"
        elif priority_score >= 2:
            base_percentage = 3   # Low-medium priority
            tier = "Speculative"
        else:
            base_percentage = 1   # Low priority
            tier = "Deep League Only"
        
        # Adjust for league size (more competitive = higher bids)
        team_count = league_rules["team_count"]
        if team_count >= 14:
            base_percentage += 3  # More competitive
        elif team_count <= 10:
            base_percentage -= 2  # Less competitive
        
        # Calculate actual bid amounts if budget is available
        if waiver_budget:
            suggested_bid = max(1, int(waiver_budget * base_percentage / 100))
            min_amount = max(1, int(waiver_budget * min(base_percentage - 3, 1) / 100))
            max_amount = min(waiver_budget, int(waiver_budget * (base_percentage + 3) / 100))
            range_text = f"${min_amount}-${max_amount}"
        else:
            suggested_bid = None
            range_text = f"{max(1, base_percentage - 3)}-{base_percentage + 3}%"
        
        return {
            "suggestion_type": "FAAB",
            "percentage": base_percentage,
            "suggested_bid": suggested_bid,
            "range": range_text,
            "tier": tier,
            "reasoning": f"Based on {priority_score:.1f} priority score in {team_count}-team FAAB league"
        }
    
    def _generate_waiver_priority_suggestion(self, priority_score: float, league_rules: Dict[str, Any], player: Dict[str, Any]) -> Dict[str, Any]:
        """Generate suggestions for waiver priority leagues with competitor analysis"""
        league_id = league_rules["league_id"]
        position = player.get("position", "")
        
        # Get competitor analysis for this league
        competitor_insights = self._analyze_league_competition(league_id, position)
        
        # Determine claim urgency
        if priority_score >= 8:
            urgency = "Immediate"
            tier = "Must-claim"
            claim_advice = "Use high waiver priority"
        elif priority_score >= 6:
            urgency = "High"
            tier = "Strong claim"
            claim_advice = "Worth burning waiver priority"
        elif priority_score >= 4:
            urgency = "Medium"
            tier = "Good claim"
            claim_advice = "Claim if waiver position allows"
        else:
            urgency = "Low"
            tier = "Speculative"
            claim_advice = "Only claim with low waiver position"
        
        # Add competitor context
        competitor_threat = competitor_insights.get("threat_level", "unknown")
        competition_reasoning = []
        
        if competitor_threat == "high":
            claim_advice += " - High competition expected"
            competition_reasoning.append("Multiple managers likely targeting")
        elif competitor_threat == "medium":
            competition_reasoning.append("Some competition expected")
        else:
            competition_reasoning.append("Lower competition likely")
        
        # Add position-specific insights
        position_insights = competitor_insights.get("position_insights", {})
        if position_insights.get("high_demand", False):
            competition_reasoning.append(f"{position} is in high demand in this league")
        
        return {
            "suggestion_type": "WAIVER_PRIORITY",
            "urgency": urgency,
            "tier": tier,
            "claim_advice": claim_advice,
            "competitor_insights": competitor_insights,
            "reasoning": f"Priority score {priority_score:.1f} - {' • '.join(competition_reasoning)}"
        }
    
    def _generate_enhanced_recommendation_reason(self, player: Dict, roster_needs: Dict[str, int], 
                                               trending_player: Dict, league_rules: Dict[str, Any]) -> str:
        """Generate enhanced reasoning with league context"""
        position = player.get("position", "")
        trend_count = trending_player.get("trend_count", 0)
        position_need = roster_needs.get(position, 0)
        
        # Base reason
        reasons = []
        
        if trend_count > 50:
            reasons.append(f"Heavily trending ({trend_count} adds)")
        elif trend_count > 20:
            reasons.append(f"Trending pickup ({trend_count} adds)")
        
        if position_need >= 3:
            reasons.append(f"High {position} need")
        elif position_need >= 1:
            reasons.append(f"Addresses {position} depth")
        
        # League-specific reasons
        ppr_value = league_rules["ppr_value"]
        scoring_type = league_rules["scoring_type"].replace("_", " ").title()
        ai_context = league_rules["ai_context"]
        
        if position == "WR" and ppr_value > 0:
            reasons.append(f"WR value in {scoring_type}")
        elif position == "RB" and ppr_value < 0.5:
            reasons.append(f"RB premium in {scoring_type}")
        elif position == "TE" and league_rules["team_count"] >= 12:
            reasons.append("TE scarcity in large league")
        elif position == "QB" and ai_context["qb_premium"]:
            superflex_config = league_rules["superflex_config"]
            if superflex_config["has_superflex"]:
                reasons.append("High QB value in superflex")
            elif superflex_config["is_2qb"]:
                reasons.append("Critical QB in 2QB league")
        
        # Player-specific reasons
        age = player.get("age")
        if age and age < 25:
            reasons.append("Young upside play")
        
        if not reasons:
            reasons.append("Speculative add with upside")
        
        return " • ".join(reasons)
    
    def _get_position_value_in_league(self, position: str, league_rules: Dict[str, Any]) -> str:
        """Get position value assessment for the specific league"""
        ppr_value = league_rules["ppr_value"]
        ai_context = league_rules["ai_context"]
        
        if position == "QB" and ai_context["qb_premium"]:
            superflex_config = league_rules["superflex_config"]
            if superflex_config["is_2qb"]:
                return "Elite (2QB League)"
            elif superflex_config["has_superflex"]:
                return "Premium (Superflex)"
            else:
                return "High"
        elif position == "WR":
            if ppr_value >= 1:
                return "Premium (Full PPR)"
            elif ppr_value >= 0.5:
                return "High (Half PPR)"
            else:
                return "Standard"
        elif position == "RB":
            if ppr_value < 0.5:
                return "Premium (Standard)"
            else:
                return "High (PPR)"
        elif position == "TE":
            if league_rules["team_count"] >= 12:
                return "Premium (Large League)"
            else:
                return "Standard"
        else:
            return "Standard"
    
    def _analyze_league_competition(self, league_id: int, position: str) -> Dict[str, Any]:
        """Analyze competition for waiver claims in this league"""
        try:
            # Get existing competitor analysis
            competitor_analyses = self.db.query(CompetitorAnalysis).filter(
                CompetitorAnalysis.league_id == league_id
            ).all()
            
            if not competitor_analyses:
                # No historical data yet, return basic analysis
                return {
                    "threat_level": "unknown",
                    "position_insights": {"high_demand": False},
                    "active_managers": 0,
                    "reasoning": "No historical data available for competition analysis"
                }
            
            # Analyze position demand
            position_demand_scores = []
            total_managers = len(competitor_analyses)
            active_managers = 0
            
            for analysis in competitor_analyses:
                if analysis.waiver_aggressiveness_score and analysis.waiver_aggressiveness_score > 30:
                    active_managers += 1
                
                # Check if this manager commonly targets this position
                preferred_positions = analysis.preferred_positions or {}
                position_preference = preferred_positions.get(position, 0)
                position_demand_scores.append(position_preference)
            
            # Calculate threat level
            avg_position_interest = sum(position_demand_scores) / len(position_demand_scores) if position_demand_scores else 0
            active_manager_ratio = active_managers / total_managers if total_managers > 0 else 0
            
            if avg_position_interest > 0.6 and active_manager_ratio > 0.5:
                threat_level = "high"
            elif avg_position_interest > 0.3 or active_manager_ratio > 0.3:
                threat_level = "medium"
            else:
                threat_level = "low"
            
            return {
                "threat_level": threat_level,
                "position_insights": {
                    "high_demand": avg_position_interest > 0.5,
                    "avg_interest": round(avg_position_interest, 2)
                },
                "active_managers": active_managers,
                "total_managers": total_managers,
                "reasoning": f"{active_managers}/{total_managers} active managers, {avg_position_interest:.1%} avg {position} interest"
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze league competition for league {league_id}: {str(e)}")
            return {
                "threat_level": "unknown",
                "position_insights": {"high_demand": False},
                "active_managers": 0,
                "reasoning": "Error analyzing competition data"
            }
    
    # ============================================================================
    # HISTORICAL DATA SYNC AND COMPETITOR ANALYSIS
    # ============================================================================
    
    async def sync_historical_league_data(self, league_id: int, seasons: List[int]) -> bool:
        """Sync historical data for multiple seasons and generate competitor analysis"""
        try:
            league = self.db.query(FantasyLeague).filter(FantasyLeague.id == league_id).first()
            if not league:
                logger.error(f"League {league_id} not found")
                return False
            
            platform_interface = self.platforms.get(league.platform)
            if not platform_interface:
                logger.error(f"Platform {league.platform} not supported")
                return False
            
            for season in seasons:
                logger.info(f"Syncing historical data for league {league_id}, season {season}")
                
                # Get historical data from platform
                historical_data = await platform_interface.get_historical_league_data(
                    league.platform_league_id, season
                )
                
                if not historical_data:
                    logger.warning(f"No historical data available for season {season}")
                    continue
                
                # Store historical data
                await self._store_historical_data(league_id, season, historical_data)
                
                # Generate competitor analysis
                await self._analyze_and_store_competitor_data(league_id, season, historical_data)
            
            logger.info(f"Successfully synced historical data for {len(seasons)} seasons")
            return True
            
        except Exception as e:
            logger.error(f"Failed to sync historical data for league {league_id}: {str(e)}")
            return False
    
    async def _store_historical_data(self, league_id: int, season: int, historical_data: Dict[str, Any]):
        """Store historical league data in database"""
        try:
            # Check if data already exists
            existing = self.db.query(LeagueHistoricalData).filter(
                and_(
                    LeagueHistoricalData.league_id == league_id,
                    LeagueHistoricalData.season == season
                )
            ).first()
            
            if existing:
                # Update existing record
                existing.teams_data = historical_data.get('teams_data', [])
                existing.transactions_data = historical_data.get('transactions_data', [])
                existing.standings_data = historical_data.get('standings_data', [])
                existing.waiver_type = historical_data.get('waiver_settings', {}).get('waiver_type')
                existing.waiver_budget = historical_data.get('waiver_settings', {}).get('waiver_budget')
                existing.last_updated = datetime.utcnow()
            else:
                # Create new record
                league_info = historical_data.get('league_info', {})
                
                historical_record = LeagueHistoricalData(
                    league_id=league_id,
                    season=season,
                    team_count=league_info.get('total_rosters'),
                    waiver_type=historical_data.get('waiver_settings', {}).get('waiver_type'),
                    waiver_budget=historical_data.get('waiver_settings', {}).get('waiver_budget'),
                    scoring_type=self._determine_scoring_from_settings(league_info.get('scoring_settings', {})),
                    teams_data=historical_data.get('teams_data', []),
                    transactions_data=historical_data.get('transactions_data', []),
                    standings_data=historical_data.get('standings_data', [])
                )
                self.db.add(historical_record)
            
            self.db.commit()
            logger.info(f"Stored historical data for league {league_id}, season {season}")
            
        except Exception as e:
            logger.error(f"Failed to store historical data: {str(e)}")
            self.db.rollback()
    
    async def _analyze_and_store_competitor_data(self, league_id: int, season: int, historical_data: Dict[str, Any]):
        """Analyze competitor patterns and store analysis"""
        try:
            teams_data = historical_data.get('teams_data', [])
            transactions_data = historical_data.get('transactions_data', [])
            waiver_settings = historical_data.get('waiver_settings', {})
            
            # Group transactions by team
            team_transactions = {}
            for transaction in transactions_data:
                for roster_id in transaction.get('roster_ids', []):
                    if roster_id not in team_transactions:
                        team_transactions[roster_id] = []
                    team_transactions[roster_id].append(transaction)
            
            # Analyze each team's patterns
            for team in teams_data:
                roster_id = team['roster_id']
                team_transactions_list = team_transactions.get(roster_id, [])
                
                # Find corresponding database team
                db_team = self.db.query(FantasyTeam).filter(
                    and_(
                        FantasyTeam.league_id == league_id,
                        FantasyTeam.platform_team_id == str(roster_id)
                    )
                ).first()
                
                if not db_team:
                    continue
                
                analysis = self._analyze_team_patterns(team_transactions_list, waiver_settings)
                
                # Store or update competitor analysis
                existing_analysis = self.db.query(CompetitorAnalysis).filter(
                    and_(
                        CompetitorAnalysis.league_id == league_id,
                        CompetitorAnalysis.team_id == db_team.id
                    )
                ).first()
                
                if existing_analysis:
                    # Update with new season data
                    seasons_analyzed = existing_analysis.seasons_analyzed or []
                    if season not in seasons_analyzed:
                        seasons_analyzed.append(season)
                    
                    # Combine analysis (weighted average for multi-season data)
                    existing_analysis.seasons_analyzed = seasons_analyzed
                    self._merge_competitor_analysis(existing_analysis, analysis)
                else:
                    # Create new analysis
                    new_analysis = CompetitorAnalysis(
                        league_id=league_id,
                        team_id=db_team.id,
                        seasons_analyzed=[season],
                        **analysis
                    )
                    self.db.add(new_analysis)
            
            self.db.commit()
            logger.info(f"Analyzed competitor data for league {league_id}, season {season}")
            
        except Exception as e:
            logger.error(f"Failed to analyze competitor data: {str(e)}")
            self.db.rollback()
    
    def _analyze_team_patterns(self, transactions: List[Dict], waiver_settings: Dict) -> Dict[str, Any]:
        """Analyze individual team's transaction patterns"""
        waiver_adds = [t for t in transactions if t.get('type') == 'waiver' and t.get('adds')]
        free_agent_adds = [t for t in transactions if t.get('type') == 'free_agent' and t.get('adds')]
        
        total_adds = len(waiver_adds) + len(free_agent_adds)
        
        # Position preferences
        position_counts = {}
        for transaction in waiver_adds + free_agent_adds:
            adds = transaction.get('adds', {})
            for player_id in adds.keys():
                # Would need player position lookup here - simplified for now
                position = "UNKNOWN"  # TODO: Look up player position
                position_counts[position] = position_counts.get(position, 0) + 1
        
        # FAAB analysis (if applicable)
        faab_data = {}
        if waiver_settings.get('waiver_type') == 'FAAB':
            faab_bids = []
            for transaction in waiver_adds:
                waiver_budget = transaction.get('waiver_budget', {})
                for roster_id, bid_amount in waiver_budget.items():
                    if bid_amount > 0:
                        faab_bids.append(bid_amount)
            
            if faab_bids:
                faab_data = {
                    'avg_faab_spent_per_season': sum(faab_bids),
                    'high_faab_bid_threshold': max(faab_bids) if faab_bids else 0,
                    'faab_conservation_tendency': self._determine_faab_tendency(faab_bids, waiver_settings.get('waiver_budget', 100))
                }
        
        return {
            'avg_waiver_adds_per_season': float(total_adds),
            'preferred_positions': position_counts,
            'waiver_aggressiveness_score': min(total_adds * 5, 100),  # Simple scoring
            **faab_data
        }
    
    def _determine_faab_tendency(self, bids: List[int], total_budget: int) -> str:
        """Determine FAAB spending tendency"""
        if not bids or total_budget == 0:
            return "unknown"
        
        total_spent = sum(bids)
        spending_rate = total_spent / total_budget
        
        if spending_rate > 0.8:
            return "aggressive"
        elif spending_rate > 0.4:
            return "moderate"
        else:
            return "conservative"
    
    def _merge_competitor_analysis(self, existing: CompetitorAnalysis, new_analysis: Dict[str, Any]):
        """Merge new season analysis with existing multi-season analysis"""
        # Simple averaging for now - could be more sophisticated
        seasons_count = len(existing.seasons_analyzed) + 1
        
        if existing.avg_waiver_adds_per_season:
            existing.avg_waiver_adds_per_season = (
                (existing.avg_waiver_adds_per_season * (seasons_count - 1) + new_analysis['avg_waiver_adds_per_season']) 
                / seasons_count
            )
        else:
            existing.avg_waiver_adds_per_season = new_analysis['avg_waiver_adds_per_season']
        
        # Merge position preferences
        existing_positions = existing.preferred_positions or {}
        new_positions = new_analysis.get('preferred_positions', {})
        merged_positions = existing_positions.copy()
        
        for position, count in new_positions.items():
            merged_positions[position] = merged_positions.get(position, 0) + count
        
        existing.preferred_positions = merged_positions
    
    def _determine_scoring_from_settings(self, scoring_settings: Dict[str, Any]) -> str:
        """Determine scoring type from scoring settings"""
        rec_points = scoring_settings.get('rec', 0)
        if rec_points >= 1:
            return 'ppr'
        elif rec_points >= 0.5:
            return 'half_ppr'
        else:
            return 'standard'