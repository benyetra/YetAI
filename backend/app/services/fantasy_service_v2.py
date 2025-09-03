"""
Streamlined Fantasy Service V2
Simple, efficient service layer for the new V2 schema
"""
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from app.models.database_models import User
from typing import Dict, List, Optional, Any
import json
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class FantasyServiceV2:
    """Streamlined fantasy service using V2 schema"""
    
    def __init__(self, db: Session):
        self.db = db
        # Import models here to avoid circular imports
        from app.models.fantasy_models_v2 import League, Team, Player, Transaction, WeeklyProjection, TradeAnalysis
        self.League = League
        self.Team = Team
        self.Player = Player
        self.Transaction = Transaction
        self.WeeklyProjection = WeeklyProjection
        self.TradeAnalysis = TradeAnalysis
    
    # LEAGUE OPERATIONS
    
    def get_user_leagues(self, user_id: int, season: Optional[int] = None):
        """Get all leagues for a user, optionally filtered by season"""
        query = self.db.query(self.League).filter(self.League.user_id == user_id)
        if season:
            query = query.filter(League.season == season)
        return query.order_by(desc(League.season), League.name).all()
    
    def get_league_by_external_id(self, external_league_id: str, user_id: int) -> Optional[League]:
        """Get league by external ID (e.g., Sleeper league ID)"""
        return self.db.query(League).filter(
            League.external_league_id == external_league_id,
            League.user_id == user_id
        ).first()
    
    def get_league_standings(self, league_id: int) -> List[Dict[str, Any]]:
        """Get current standings for a league"""
        teams = self.db.query(Team).filter(
            Team.league_id == league_id
        ).order_by(desc(Team.wins), desc(Team.points_for)).all()
        
        standings = []
        for i, team in enumerate(teams):
            standings.append({
                "rank": i + 1,
                "team_id": team.id,
                "team_name": team.team_name or f"Team {team.external_team_id}",
                "owner_name": team.owner_name or "Unknown",
                "wins": team.wins,
                "losses": team.losses,
                "ties": team.ties,
                "points_for": team.points_for,
                "points_against": team.points_against,
                "win_percentage": team.win_percentage,
                "total_players": len(team.active_players),
                "external_team_id": team.external_team_id
            })
        
        return standings
    
    # TEAM OPERATIONS
    
    def get_team_by_external_id(self, external_team_id: str, league_id: Optional[int] = None) -> Optional[Team]:
        """Get team by external ID, optionally scoped to league"""
        query = self.db.query(Team).filter(Team.external_team_id == external_team_id)
        if league_id:
            query = query.filter(Team.league_id == league_id)
        
        # Prioritize current season (2025)
        teams = query.join(League).order_by(desc(League.season)).all()
        return teams[0] if teams else None
    
    def get_team_analysis(self, team_id: int) -> Dict[str, Any]:
        """Get comprehensive team analysis"""
        team = self.db.query(Team).filter(Team.id == team_id).first()
        if not team:
            raise ValueError(f"Team {team_id} not found")
        
        # Get player details
        player_details = []
        for player_id in team.active_players:
            player = self.db.query(Player).filter(Player.sleeper_id == str(player_id)).first()
            if player:
                player_details.append({
                    "id": player_id,
                    "name": player.display_name,
                    "position": player.position,
                    "nfl_team": player.nfl_team,
                    "is_starter": player_id in (team.starting_lineup or []),
                    "is_injured": player.is_injured,
                    "trade_value": player.trade_value or 0.0,
                    "status": player.status
                })
        
        # Analyze roster composition
        position_analysis = self._analyze_team_positions(player_details)
        
        # Categorize players for trading
        valuable_players = [p for p in player_details if p["is_starter"] and p["trade_value"] > 20]
        expendable_players = [p for p in player_details if not p["is_starter"] and p["position"] in ["RB", "WR", "TE"]]
        surplus_players = self._identify_surplus_players(player_details, position_analysis)
        
        return {
            "team_info": {
                "team_id": team.id,
                "team_name": team.team_name,
                "owner_name": team.owner_name,
                "record": f"{team.wins}-{team.losses}-{team.ties}",
                "points_for": team.points_for,
                "points_against": team.points_against,
                "win_percentage": team.win_percentage,
                "league_id": team.league_id
            },
            "roster_analysis": {
                "total_players": len(player_details),
                "starters": len([p for p in player_details if p["is_starter"]]),
                "bench_players": len([p for p in player_details if not p["is_starter"]]),
                "injured_players": len([p for p in player_details if p["is_injured"]]),
                "position_breakdown": position_analysis["position_counts"],
                "position_strengths": position_analysis["strengths"],
                "position_needs": position_analysis["needs"]
            },
            "tradeable_assets": {
                "valuable_players": valuable_players,
                "expendable_players": expendable_players,
                "surplus_players": surplus_players
            },
            "all_players": player_details
        }
    
    def _analyze_team_positions(self, players: List[Dict]) -> Dict[str, Any]:
        """Analyze team position strengths and needs"""
        position_counts = {}
        starter_counts = {}
        
        for player in players:
            pos = player["position"]
            if pos not in position_counts:
                position_counts[pos] = {"total": 0, "starters": 0}
            
            position_counts[pos]["total"] += 1
            if player["is_starter"]:
                position_counts[pos]["starters"] += 1
        
        # Calculate position strengths (simplified algorithm)
        strengths = {}
        needs = {}
        
        position_targets = {
            "QB": {"ideal_starters": 1, "ideal_total": 2},
            "RB": {"ideal_starters": 2, "ideal_total": 4},
            "WR": {"ideal_starters": 2, "ideal_total": 5},
            "TE": {"ideal_starters": 1, "ideal_total": 2},
            "K": {"ideal_starters": 1, "ideal_total": 1},
            "DEF": {"ideal_starters": 1, "ideal_total": 1}
        }
        
        for pos, targets in position_targets.items():
            counts = position_counts.get(pos, {"total": 0, "starters": 0})
            
            # Strength calculation (0-100)
            strength_score = min(100, (counts["total"] / targets["ideal_total"]) * 100)
            strengths[pos] = strength_score
            
            # Need calculation (higher = more need)
            if counts["total"] < targets["ideal_total"]:
                need_level = (targets["ideal_total"] - counts["total"]) * 20
                needs[pos] = min(100, need_level)
            else:
                needs[pos] = 0
        
        return {
            "position_counts": position_counts,
            "strengths": strengths,
            "needs": needs
        }
    
    def _identify_surplus_players(self, players: List[Dict], position_analysis: Dict) -> List[Dict]:
        """Identify players that could be traded due to position surplus"""
        surplus = []
        
        # Group players by position
        by_position = {}
        for player in players:
            pos = player["position"]
            if pos not in by_position:
                by_position[pos] = []
            by_position[pos].append(player)
        
        # Identify surplus at each position
        for pos, players_at_pos in by_position.items():
            if pos in ["RB", "WR", "TE"] and len(players_at_pos) > 3:
                # Sort by trade value, keep top 3
                sorted_players = sorted(players_at_pos, key=lambda x: x["trade_value"], reverse=True)
                surplus.extend(sorted_players[3:])
        
        return surplus
    
    # PLAYER OPERATIONS
    
    def get_player_by_external_id(self, external_id: str, platform: str = "sleeper") -> Optional[Player]:
        """Get player by external ID"""
        if platform == "sleeper":
            return self.db.query(Player).filter(Player.sleeper_id == external_id).first()
        elif platform == "yahoo":
            return self.db.query(Player).filter(Player.yahoo_id == external_id).first()
        elif platform == "espn":
            return self.db.query(Player).filter(Player.espn_id == external_id).first()
        return None
    
    def search_players(self, query: str, position: Optional[str] = None, limit: int = 20) -> List[Player]:
        """Search players by name or position"""
        search_query = self.db.query(Player)
        
        if query:
            search_query = search_query.filter(
                Player.full_name.ilike(f"%{query}%")
            )
        
        if position:
            search_query = search_query.filter(Player.position == position)
        
        return search_query.order_by(
            desc(Player.trade_value),
            Player.full_name
        ).limit(limit).all()
    
    def get_top_players_by_position(self, position: str, limit: int = 50) -> List[Player]:
        """Get top players at a position by trade value"""
        return self.db.query(Player).filter(
            Player.position == position,
            Player.trade_value.isnot(None)
        ).order_by(desc(Player.trade_value)).limit(limit).all()
    
    # TRADE OPERATIONS
    
    def analyze_trade(self, team1_id: int, team1_gives: List[str], team1_receives: List[str],
                     team2_id: int, team2_gives: List[str], team2_receives: List[str]) -> Dict[str, Any]:
        """Analyze a potential trade between two teams"""
        
        team1 = self.db.query(Team).filter(Team.id == team1_id).first()
        team2 = self.db.query(Team).filter(Team.id == team2_id).first()
        
        if not team1 or not team2:
            raise ValueError("One or both teams not found")
        
        # Get player details for trade
        team1_gives_players = [self.get_player_by_external_id(pid) for pid in team1_gives]
        team1_receives_players = [self.get_player_by_external_id(pid) for pid in team1_receives]
        team2_gives_players = [self.get_player_by_external_id(pid) for pid in team2_gives]
        team2_receives_players = [self.get_player_by_external_id(pid) for pid in team2_receives]
        
        # Calculate trade values
        team1_gives_value = sum(p.trade_value or 0 for p in team1_gives_players if p)
        team1_receives_value = sum(p.trade_value or 0 for p in team1_receives_players if p)
        team2_gives_value = sum(p.trade_value or 0 for p in team2_gives_players if p)
        team2_receives_value = sum(p.trade_value or 0 for p in team2_receives_players if p)
        
        # Analysis
        team1_net_value = team1_receives_value - team1_gives_value
        team2_net_value = team2_receives_value - team2_gives_value
        
        fairness_score = 100 - abs(team1_net_value) * 2  # Penalize unfair trades
        fairness_score = max(0, min(100, fairness_score))
        
        trade_analysis = {
            "trade_summary": {
                "team1": {
                    "team_name": team1.team_name,
                    "gives_value": team1_gives_value,
                    "receives_value": team1_receives_value,
                    "net_value": team1_net_value
                },
                "team2": {
                    "team_name": team2.team_name,
                    "gives_value": team2_gives_value,
                    "receives_value": team2_receives_value,
                    "net_value": team2_net_value
                }
            },
            "analysis": {
                "fairness_score": fairness_score,
                "winner": team1.team_name if team1_net_value > team2_net_value else team2.team_name,
                "trade_grade": self._calculate_trade_grade(fairness_score),
                "recommendation": "Accept" if fairness_score > 70 else "Consider" if fairness_score > 50 else "Decline"
            },
            "player_details": {
                "team1_gives": [{"name": p.display_name, "position": p.position, "value": p.trade_value} for p in team1_gives_players if p],
                "team1_receives": [{"name": p.display_name, "position": p.position, "value": p.trade_value} for p in team1_receives_players if p],
                "team2_gives": [{"name": p.display_name, "position": p.position, "value": p.trade_value} for p in team2_gives_players if p],
                "team2_receives": [{"name": p.display_name, "position": p.position, "value": p.trade_value} for p in team2_receives_players if p]
            }
        }
        
        return trade_analysis
    
    def _calculate_trade_grade(self, fairness_score: float) -> str:
        """Convert fairness score to letter grade"""
        if fairness_score >= 90:
            return "A+"
        elif fairness_score >= 85:
            return "A"
        elif fairness_score >= 80:
            return "A-"
        elif fairness_score >= 75:
            return "B+"
        elif fairness_score >= 70:
            return "B"
        elif fairness_score >= 65:
            return "B-"
        elif fairness_score >= 60:
            return "C+"
        elif fairness_score >= 55:
            return "C"
        elif fairness_score >= 50:
            return "C-"
        elif fairness_score >= 45:
            return "D+"
        elif fairness_score >= 40:
            return "D"
        else:
            return "F"
    
    # ANALYTICS AND INSIGHTS
    
    def get_league_analytics(self, league_id: int) -> Dict[str, Any]:
        """Get comprehensive league analytics"""
        league = self.db.query(League).filter(League.id == league_id).first()
        if not league:
            raise ValueError(f"League {league_id} not found")
        
        teams = self.db.query(Team).filter(Team.league_id == league_id).all()
        
        # Calculate league-wide stats
        total_points = sum(team.points_for for team in teams)
        avg_points = total_points / len(teams) if teams else 0
        
        # Most/least points
        highest_scoring = max(teams, key=lambda t: t.points_for) if teams else None
        lowest_scoring = min(teams, key=lambda t: t.points_for) if teams else None
        
        # Trading activity
        recent_trades = self.db.query(Transaction).filter(
            Transaction.league_id == league_id,
            Transaction.transaction_type == "trade",
            Transaction.processed_at >= datetime.utcnow() - timedelta(days=30)
        ).count()
        
        return {
            "league_info": {
                "name": league.name,
                "season": league.season,
                "total_teams": len(teams),
                "scoring_type": league.scoring_type,
                "current_week": league.current_week
            },
            "scoring_stats": {
                "total_points": total_points,
                "average_points": avg_points,
                "highest_scoring_team": highest_scoring.team_name if highest_scoring else None,
                "highest_points": highest_scoring.points_for if highest_scoring else 0,
                "lowest_scoring_team": lowest_scoring.team_name if lowest_scoring else None,
                "lowest_points": lowest_scoring.points_for if lowest_scoring else 0
            },
            "activity_stats": {
                "recent_trades": recent_trades,
                "active_teams": len([t for t in teams if t.last_synced >= datetime.utcnow() - timedelta(days=7)])
            }
        }
    
    def get_trade_recommendations(self, team_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Get AI-powered trade recommendations for a team"""
        team_analysis = self.get_team_analysis(team_id)
        
        # Simple recommendation logic (can be enhanced with AI)
        recommendations = []
        
        # Identify team needs
        needs = team_analysis["roster_analysis"]["position_needs"]
        top_need = max(needs.items(), key=lambda x: x[1]) if needs else None
        
        if top_need:
            needed_position = top_need[0]
            
            # Find available players at needed position
            available_players = self.get_top_players_by_position(needed_position, limit * 2)
            
            # Find expendable players from current team
            expendable = team_analysis["tradeable_assets"]["expendable_players"]
            
            for player in available_players[:limit]:
                if expendable:
                    target_player = expendable[0]  # Simplistic - take first expendable
                    recommendations.append({
                        "type": "player_for_player",
                        "give": target_player,
                        "receive": {
                            "name": player.display_name,
                            "position": player.position,
                            "trade_value": player.trade_value
                        },
                        "reason": f"Upgrade at {needed_position} position",
                        "confidence": 75
                    })
        
        return recommendations
    
    # UTILITY METHODS
    
    def update_player_trade_values(self, player_values: Dict[str, float]):
        """Bulk update player trade values"""
        for player_id, value in player_values.items():
            player = self.get_player_by_external_id(player_id)
            if player:
                player.trade_value = value
        
        self.db.commit()
    
    def sync_league_current_week(self, league_id: int, current_week: int):
        """Update league's current week"""
        league = self.db.query(League).filter(League.id == league_id).first()
        if league:
            league.current_week = current_week
            league.last_synced = datetime.utcnow()
            self.db.commit()