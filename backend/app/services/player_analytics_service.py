"""
Player Analytics Service - Advanced player usage and performance analytics
"""
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, desc
from datetime import datetime, timedelta
import statistics
from app.models.fantasy_models import (
    FantasyPlayer, PlayerAnalytics, PlayerTrends, PlayerProjection
)

class PlayerAnalyticsService:
    """Service for managing and calculating advanced player analytics"""
    
    def __init__(self, db: Session):
        self.db = db
        
    async def get_player_analytics(
        self, 
        player_id: int, 
        weeks: Optional[List[int]] = None,
        season: int = 2024
    ) -> List[Dict]:
        """Get analytics data for a specific player"""
        try:
            # First check if the player exists
            player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
            if not player:
                return []
            
            query = self.db.query(PlayerAnalytics).filter(
                PlayerAnalytics.player_id == player_id,
                PlayerAnalytics.season == season
            )
            
            if weeks:
                query = query.filter(PlayerAnalytics.week.in_(weeks))
                
            analytics = query.order_by(PlayerAnalytics.week).all()
            
            return [self._format_analytics_data(analytic) for analytic in analytics]
        except Exception as e:
            # For debugging - return empty list instead of crashing
            print(f"Error in get_player_analytics: {str(e)}")
            return []
    
    async def calculate_usage_trends(
        self, 
        player_id: int, 
        weeks: List[int],
        season: int = 2024
    ) -> Dict:
        """Calculate usage trends over specified weeks"""
        try:
            analytics = await self.get_player_analytics(player_id, weeks, season)
            
            if len(analytics) < 2:
                return {}
                
            # Calculate trends for key metrics
            snap_shares = [a['snap_percentage'] for a in analytics if a['snap_percentage']]
            target_shares = [a['target_share'] for a in analytics if a['target_share']]
            red_zone_shares = [a['red_zone_share'] for a in analytics if a['red_zone_share']]
            
            trends = {}
            
            if snap_shares:
                trends['snap_share_trend'] = self._calculate_trend(snap_shares)
                trends['avg_snap_share'] = statistics.mean(snap_shares)
                trends['snap_share_consistency'] = statistics.stdev(snap_shares) if len(snap_shares) > 1 else 0
                
            if target_shares:
                trends['target_share_trend'] = self._calculate_trend(target_shares)
                trends['avg_target_share'] = statistics.mean(target_shares)
                trends['target_share_consistency'] = statistics.stdev(target_shares) if len(target_shares) > 1 else 0
                
            if red_zone_shares:
                trends['red_zone_usage_trend'] = self._calculate_trend(red_zone_shares)
                trends['avg_red_zone_share'] = statistics.mean(red_zone_shares)
                
            return trends
        except Exception as e:
            print(f"Error in calculate_usage_trends: {str(e)}")
            return {}
    
    async def calculate_efficiency_metrics(
        self, 
        player_id: int, 
        weeks: List[int],
        season: int = 2024
    ) -> Dict:
        """Calculate advanced efficiency metrics"""
        try:
            analytics = await self.get_player_analytics(player_id, weeks, season)
            
            if not analytics:
                return {}
                
            # Calculate efficiency metrics
            efficiency = {
                'points_per_snap': [],
                'points_per_target': [],
                'points_per_touch': [],
                'red_zone_efficiency': [],
                'consistency_metrics': {}
            }
            
            for week_data in analytics:
                if week_data.get('points_per_snap'):
                    efficiency['points_per_snap'].append(week_data['points_per_snap'])
                if week_data.get('points_per_target'):
                    efficiency['points_per_target'].append(week_data['points_per_target'])
                if week_data.get('points_per_touch'):
                    efficiency['points_per_touch'].append(week_data['points_per_touch'])
                if week_data.get('red_zone_efficiency'):
                    efficiency['red_zone_efficiency'].append(week_data['red_zone_efficiency'])
            
            # Calculate averages and trends
            result = {}
            for metric, values in efficiency.items():
                if values and metric != 'consistency_metrics':
                    result[f'avg_{metric}'] = statistics.mean(values)
                    result[f'{metric}_trend'] = self._calculate_trend(values)
                    result[f'{metric}_variance'] = statistics.stdev(values) if len(values) > 1 else 0
                    
            return result
        except Exception as e:
            print(f"Error in calculate_efficiency_metrics: {str(e)}")
            return {}
    
    async def identify_breakout_candidates(
        self, 
        position: str,
        season: int = 2024,
        min_weeks: int = 3
    ) -> List[Dict]:
        """Identify players with increasing usage trends (breakout candidates)"""
        
        # Get players with sufficient data
        recent_weeks = list(range(max(1, self._get_current_week() - min_weeks), self._get_current_week() + 1))
        
        # Query for players with positive trends
        subquery = self.db.query(PlayerAnalytics.player_id).filter(
            PlayerAnalytics.season == season,
            PlayerAnalytics.week.in_(recent_weeks)
        ).group_by(PlayerAnalytics.player_id).having(
            func.count(PlayerAnalytics.week) >= min_weeks
        )
        
        candidates = []
        
        for player_query in subquery:
            player_id = player_query.player_id
            trends = await self.calculate_usage_trends(player_id, recent_weeks, season)
            
            # Breakout criteria
            if (trends.get('snap_share_trend', 0) > 5 and  # Increasing snap share
                trends.get('target_share_trend', 0) > 3 and  # Increasing target share
                trends.get('avg_snap_share', 0) > 40):  # Meaningful snap share
                
                player = self.db.query(FantasyPlayer).get(player_id)
                if player and player.position.value == position:
                    candidates.append({
                        'player_id': player_id,
                        'player_name': player.name,
                        'team': player.team,
                        'trends': trends,
                        'breakout_score': self._calculate_breakout_score(trends)
                    })
        
        # Sort by breakout score
        return sorted(candidates, key=lambda x: x['breakout_score'], reverse=True)
    
    async def get_matchup_specific_analytics(
        self, 
        player_id: int, 
        opponent_team: str,
        season: int = 2024
    ) -> Dict:
        """Get player's historical performance against specific opponent"""
        
        matchup_data = self.db.query(PlayerAnalytics).filter(
            PlayerAnalytics.player_id == player_id,
            PlayerAnalytics.opponent == opponent_team,
            PlayerAnalytics.season.in_(range(season - 2, season + 1))  # Last 3 seasons
        ).all()
        
        if not matchup_data:
            return {}
            
        # Calculate matchup-specific metrics
        fantasy_points = [d.ppr_points for d in matchup_data if d.ppr_points]
        target_shares = [d.target_share for d in matchup_data if d.target_share]
        snap_shares = [d.snap_percentage for d in matchup_data if d.snap_percentage]
        
        return {
            'games_vs_opponent': len(matchup_data),
            'avg_fantasy_points': statistics.mean(fantasy_points) if fantasy_points else 0,
            'avg_target_share': statistics.mean(target_shares) if target_shares else 0,
            'avg_snap_share': statistics.mean(snap_shares) if snap_shares else 0,
            'boom_rate': len([p for p in fantasy_points if p >= 20]) / len(fantasy_points) if fantasy_points else 0,
            'bust_rate': len([p for p in fantasy_points if p < 5]) / len(fantasy_points) if fantasy_points else 0,
            'matchup_strength': self._calculate_matchup_strength(matchup_data)
        }
    
    async def store_weekly_analytics(
        self, 
        player_id: int, 
        week: int, 
        season: int,
        analytics_data: Dict
    ) -> PlayerAnalytics:
        """Store or update weekly analytics data for a player"""
        
        # Check if analytics already exist
        existing = self.db.query(PlayerAnalytics).filter(
            PlayerAnalytics.player_id == player_id,
            PlayerAnalytics.week == week,
            PlayerAnalytics.season == season
        ).first()
        
        if existing:
            # Update existing record
            for key, value in analytics_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            analytics = existing
        else:
            # Create new record
            analytics = PlayerAnalytics(
                player_id=player_id,
                week=week,
                season=season,
                **analytics_data
            )
            self.db.add(analytics)
        
        self.db.commit()
        self.db.refresh(analytics)
        
        return analytics
    
    def _format_analytics_data(self, analytics: PlayerAnalytics) -> Dict:
        """Format analytics data for API response"""
        return {
            'week': analytics.week,
            'season': analytics.season,
            'opponent': analytics.opponent,
            
            # Snap Count Data
            'total_snaps': analytics.total_snaps,
            'snap_percentage': analytics.snap_percentage,
            'snap_share_rank': analytics.snap_share_rank,
            
            # Target Share Data
            'targets': analytics.targets,
            'target_share': analytics.target_share,
            'air_yards': analytics.air_yards,
            'air_yards_share': analytics.air_yards_share,
            'average_depth_of_target': analytics.average_depth_of_target,
            
            # Red Zone Usage
            'red_zone_targets': analytics.red_zone_targets,
            'red_zone_carries': analytics.red_zone_carries,
            'red_zone_touches': analytics.red_zone_touches,
            'red_zone_share': analytics.red_zone_share,
            'red_zone_efficiency': analytics.red_zone_efficiency,
            
            # Route Running
            'routes_run': analytics.routes_run,
            'route_participation': analytics.route_participation,
            'slot_rate': analytics.slot_rate,
            'deep_target_rate': analytics.deep_target_rate,
            
            # Efficiency Metrics
            'ppr_points': analytics.ppr_points,
            'points_per_snap': analytics.points_per_snap,
            'points_per_target': analytics.points_per_target,
            'points_per_touch': analytics.points_per_touch,
            
            # Consistency
            'boom_rate': analytics.boom_rate,
            'bust_rate': analytics.bust_rate,
            'floor_score': analytics.floor_score,
            'ceiling_score': analytics.ceiling_score,
            
            # Context
            'game_script': analytics.game_script,
            'injury_designation': analytics.injury_designation
        }
    
    def _calculate_trend(self, values: List[float]) -> float:
        """Calculate trend (slope) for a series of values"""
        if len(values) < 2:
            return 0
            
        n = len(values)
        x = list(range(n))
        
        # Simple linear regression slope
        x_mean = sum(x) / n
        y_mean = sum(values) / n
        
        numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return 0
            
        slope = numerator / denominator
        return round(slope, 2)
    
    def _calculate_breakout_score(self, trends: Dict) -> float:
        """Calculate breakout potential score"""
        score = 0
        
        # Snap share trend (weight: 30%)
        score += trends.get('snap_share_trend', 0) * 0.3
        
        # Target share trend (weight: 25%)
        score += trends.get('target_share_trend', 0) * 0.25
        
        # Red zone usage trend (weight: 20%)
        score += trends.get('red_zone_usage_trend', 0) * 0.2
        
        # Consistency bonus (weight: 15%)
        snap_consistency = 100 - (trends.get('snap_share_consistency', 100) * 5)
        score += max(0, snap_consistency) * 0.15
        
        # Average usage baseline (weight: 10%)
        avg_usage = (trends.get('avg_snap_share', 0) + trends.get('avg_target_share', 0)) / 2
        score += (avg_usage / 10) * 0.1
        
        return round(score, 2)
    
    def _calculate_matchup_strength(self, matchup_data: List[PlayerAnalytics]) -> str:
        """Determine if matchup is favorable, neutral, or tough"""
        if not matchup_data:
            return "unknown"
            
        avg_points = statistics.mean([d.ppr_points for d in matchup_data if d.ppr_points])
        
        if avg_points >= 15:
            return "favorable"
        elif avg_points >= 8:
            return "neutral"
        else:
            return "tough"
    
    def _get_current_week(self) -> int:
        """Get current NFL week (simplified for demo)"""
        # In production, this would calculate based on NFL schedule
        return 12  # Current week placeholder