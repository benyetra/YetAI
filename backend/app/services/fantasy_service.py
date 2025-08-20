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
            
            if existing_league:
                # Update existing league
                league = existing_league
                league.name = league_data.get('name', league.name)
                league.team_count = league_data.get('team_count', league.team_count)
                league.scoring_type = league_data.get('scoring_type', league.scoring_type)
            else:
                # Create new league
                league = FantasyLeague(
                    fantasy_user_id=fantasy_user.id,
                    platform=fantasy_user.platform,
                    platform_league_id=league_data['league_id'],
                    name=league_data['name'],
                    season=league_data.get('season', datetime.now().year),
                    team_count=league_data.get('team_count'),
                    scoring_type=league_data.get('scoring_type')
                )
                self.db.add(league)
                self.db.flush()  # Get league ID
            
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
                "name": league.name,
                "platform": league.platform,
                "season": league.season,
                "team_count": league.team_count,
                "scoring_type": league.scoring_type,
                "last_sync": league.last_sync,
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
    
    async def generate_waiver_wire_recommendations(self, user_id: int, week: int) -> List[Dict[str, Any]]:
        """Generate waiver wire pickup recommendations"""
        recommendations = []
        user_leagues = self.get_user_leagues(user_id)
        
        for league_data in user_leagues:
            league_id = league_data["id"]
            league = self.db.query(FantasyLeague).filter(FantasyLeague.id == league_id).first()
            
            if not league:
                continue
            
            try:
                # Get platform interface
                platform_interface = self.platforms.get(league.platform)
                if not platform_interface:
                    continue
                
                # Get trending players for recommendations
                trending_adds = await platform_interface.get_trending_players("add")
                available_players = await platform_interface.get_available_players(league.platform_league_id)
                
                # Get user's team to identify roster needs
                user_team = league_data.get("user_team")
                if not user_team:
                    continue
                
                # Analyze roster for position needs
                roster_needs = await self._analyze_roster_needs(league_id, user_team["id"])
                
                # Generate recommendations based on trending players and roster needs
                league_recommendations = self._generate_league_recommendations(
                    league_id, league_data["name"], trending_adds, available_players, roster_needs
                )
                
                recommendations.extend(league_recommendations)
                
            except Exception as e:
                logger.error(f"Failed to generate waiver recommendations for league {league_id}: {str(e)}")
                continue
        
        # Sort by priority score and return top recommendations
        recommendations.sort(key=lambda x: x["priority_score"], reverse=True)
        return recommendations[:20]  # Return top 20 recommendations
    
    async def _analyze_roster_needs(self, league_id: int, team_id: int) -> Dict[str, int]:
        """Analyze roster to identify position needs"""
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
            
            # Define typical position needs (this could be enhanced with league settings)
            typical_needs = {
                "QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1
            }
            
            # Calculate position needs (higher score = more need)
            position_needs = {}
            for pos, typical_count in typical_needs.items():
                current_count = position_counts.get(pos, 0)
                need_score = max(0, typical_count - current_count) * 2
                # Add bonus for thin positions
                if current_count <= 1:
                    need_score += 1
                position_needs[pos] = need_score
            
            return position_needs
            
        except Exception as e:
            logger.error(f"Failed to analyze roster needs: {str(e)}")
            return {}
    
    def _generate_league_recommendations(self, league_id: int, league_name: str, 
                                       trending_adds: List[Dict], available_players: List[Dict],
                                       roster_needs: Dict[str, int]) -> List[Dict[str, Any]]:
        """Generate recommendations for a specific league"""
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
            
            # Calculate priority score
            priority_score = self._calculate_priority_score(
                trending_player, player, roster_needs
            )
            
            if priority_score > 0:
                recommendation = {
                    "league_id": league_id,
                    "league_name": league_name,
                    "player_id": player_id,
                    "player_name": player.get("name", ""),
                    "position": position,
                    "team": player.get("team", "FA"),
                    "priority_score": priority_score,
                    "trend_count": trending_player.get("trend_count", 0),
                    "reason": self._generate_recommendation_reason(player, roster_needs, trending_player),
                    "suggested_fab_percentage": self._suggest_fab_percentage(priority_score),
                    "age": player.get("age"),
                    "experience": player.get("experience"),
                    "fantasy_positions": player.get("fantasy_positions", [])
                }
                recommendations.append(recommendation)
        
        return recommendations
    
    def _calculate_priority_score(self, trending_player: Dict, player: Dict, 
                                roster_needs: Dict[str, int]) -> float:
        """Calculate priority score for a waiver wire recommendation"""
        score = 0.0
        
        # Base score from trending count
        trend_count = trending_player.get("trend_count", 0)
        score += min(trend_count / 10, 5.0)  # Max 5 points from trending
        
        # Position need bonus
        position = player.get("position", "")
        position_need = roster_needs.get(position, 0)
        score += position_need * 2  # Up to 6 points for high need positions
        
        # Young player bonus (higher upside)
        age = player.get("age")
        if age and age < 26:
            score += 1.0
        
        # Experience factor (not too rookie, not too veteran)
        experience = player.get("experience", 0)
        if 1 <= experience <= 5:
            score += 0.5
        
        # Multi-position eligibility bonus
        fantasy_positions = player.get("fantasy_positions", [])
        if len(fantasy_positions) > 1:
            score += 0.5
        
        return round(score, 2)
    
    def _generate_recommendation_reason(self, player: Dict, roster_needs: Dict, 
                                     trending_player: Dict) -> str:
        """Generate human-readable recommendation reason"""
        position = player.get("position", "")
        trend_count = trending_player.get("trend_count", 0)
        position_need = roster_needs.get(position, 0)
        
        reasons = []
        
        if trend_count > 20:
            reasons.append(f"Trending heavily ({trend_count} adds)")
        elif trend_count > 10:
            reasons.append(f"Popular pickup ({trend_count} adds)")
        
        if position_need >= 2:
            reasons.append(f"High {position} need")
        elif position_need >= 1:
            reasons.append(f"Depth at {position}")
        
        age = player.get("age")
        if age and age < 24:
            reasons.append("Young upside player")
        
        fantasy_positions = player.get("fantasy_positions", [])
        if len(fantasy_positions) > 1:
            reasons.append("Position flexibility")
        
        if not reasons:
            reasons.append("Worth monitoring")
        
        return " • ".join(reasons)
    
    def _suggest_fab_percentage(self, priority_score: float) -> int:
        """Suggest FAAB percentage based on priority score"""
        if priority_score >= 8:
            return 15  # High priority
        elif priority_score >= 6:
            return 10  # Medium-high priority
        elif priority_score >= 4:
            return 5   # Medium priority
        elif priority_score >= 2:
            return 2   # Low-medium priority
        else:
            return 1   # Speculative add
    
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
    
    async def _get_league_rules_context(self, league_data: Dict[str, Any]) -> Dict[str, Any]:
        """Get league rules context for enhanced recommendations"""
        scoring_type = league_data.get("scoring_type", "standard")
        
        # PPR analysis
        ppr_value = 0
        if scoring_type == "ppr":
            ppr_value = 1.0
        elif scoring_type == "half_ppr":
            ppr_value = 0.5
        
        return {
            "league_id": league_data["id"],
            "league_name": league_data["name"],
            "scoring_type": scoring_type,
            "ppr_value": ppr_value,
            "team_count": league_data.get("team_count", 12),
            "ai_context": {
                "prioritize_volume": ppr_value > 0,  # PPR leagues favor target volume
                "rb_premium": ppr_value < 0.5,  # Standard/half-PPR favors RBs more
                "wr_target_bonus": ppr_value,  # Direct PPR bonus for WR targets
                "position_scarcity": {
                    "qb": 1, "rb": 2, "wr": 2, "te": 1, "flex": 1
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
        
        # Position scarcity adjustments
        team_count = league_rules["team_count"]
        if position == "TE" and team_count >= 12:
            # TE premium in larger leagues
            scarcity_bonus = 1.5
            league_adjusted_points += scarcity_bonus
            reasoning_factors.append(f"+{scarcity_bonus} TE scarcity")
        
        # Calculate confidence based on league context
        confidence = 65  # Base confidence
        if ai_context["prioritize_volume"] and position in ["WR", "RB"]:
            confidence += 10  # Higher confidence in PPR for volume players
        
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
                # Generate FAAB suggestions based on league context
                faab_suggestion = self._generate_faab_suggestion(priority_score, league_rules)
                
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
                    "faab_suggestion": faab_suggestion,
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
        if position == "WR" and ppr_value > 0:
            score += ppr_value * 2  # WR bonus in PPR leagues
        elif position == "RB" and ppr_value < 0.5:
            score += 1.5  # RB bonus in standard leagues
        elif position == "TE" and league_rules["team_count"] >= 12:
            score += 2.0  # TE premium in larger leagues
        
        # Young player bonus (higher upside)
        age = player.get("age")
        if age and age < 26:
            score += 1.0
        
        # Experience factor
        experience = player.get("experience")
        if experience and 2 <= experience <= 5:
            score += 0.5  # Sweet spot years
        
        return round(score, 2)
    
    def _generate_faab_suggestion(self, priority_score: float, league_rules: Dict[str, Any]) -> Dict[str, Any]:
        """Generate FAAB bidding suggestions based on priority and league context"""
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
        
        # Create suggestion ranges
        min_bid = max(1, base_percentage - 3)
        max_bid = base_percentage + 3
        
        return {
            "percentage": base_percentage,
            "range": f"{min_bid}-{max_bid}%",
            "tier": tier,
            "reasoning": f"Based on {priority_score:.1f} priority score in {team_count}-team league"
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
        
        if position == "WR" and ppr_value > 0:
            reasons.append(f"WR value in {scoring_type}")
        elif position == "RB" and ppr_value < 0.5:
            reasons.append(f"RB premium in {scoring_type}")
        elif position == "TE" and league_rules["team_count"] >= 12:
            reasons.append("TE scarcity in large league")
        
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
        
        if position == "WR":
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