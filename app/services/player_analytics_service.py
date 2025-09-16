"""
Player Analytics Service - Advanced player usage and performance analytics
"""
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, desc, text
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
            print(f"DEBUG: Querying PlayerAnalytics for player_id={player_id}, season={season}")

            # Convert fantasy_players.id to platform_player_id for analytics lookup
            platform_id_query = "SELECT platform_player_id FROM fantasy_players WHERE id = :player_id"
            platform_result = self.db.execute(text(platform_id_query), {"player_id": player_id})
            platform_row = platform_result.fetchone()

            if not platform_row:
                print(f"DEBUG: No platform_player_id found for fantasy_players.id={player_id}")
                return []

            platform_player_id = int(platform_row[0])
            print(f"DEBUG: Using platform_player_id={platform_player_id} for analytics lookup")

            # First check if the table has any data at all
            count_query = "SELECT COUNT(*) FROM player_analytics"
            count_result = self.db.execute(text(count_query))
            total_records = count_result.fetchone()[0]
            print(f"DEBUG: Total records in player_analytics table: {total_records}")

            # Check what seasons exist
            season_query = "SELECT DISTINCT season FROM player_analytics ORDER BY season"
            season_result = self.db.execute(text(season_query))
            available_seasons = [row[0] for row in season_result.fetchall()]
            print(f"DEBUG: Available seasons: {available_seasons}")

            # Use weighted query prioritizing recent data
            # Current season (2025): weight 1.0, 2024: weight 0.6, 2023: weight 0.3, older: weight 0.1
            sql_query = """
                SELECT
                    week, season, ppr_points, snap_percentage, target_share,
                    red_zone_share, points_per_snap, points_per_target,
                    boom_rate, bust_rate, floor_score, ceiling_score,
                    opponent, injury_designation, game_script,
                    CASE
                        WHEN season = 2025 THEN 1.0
                        WHEN season = 2024 THEN 0.6
                        WHEN season = 2023 THEN 0.3
                        ELSE 0.1
                    END as season_weight
                FROM player_analytics
                WHERE player_id = :player_id
                AND season >= 2022
            """

            params = {"player_id": player_id}

            if weeks and season:
                # If specific weeks requested, focus on that season
                sql_query += " AND season = :season"
                params["season"] = season
                placeholders = ",".join([f":week_{i}" for i in range(len(weeks))])
                sql_query += f" AND week IN ({placeholders})"
                for i, week in enumerate(weeks):
                    params[f"week_{i}"] = week
            elif season:
                # If season specified but no weeks, include recent seasons with weights
                sql_query += " AND season <= :season"
                params["season"] = season

            sql_query += " ORDER BY season DESC, week DESC"

            result = self.db.execute(text(sql_query), params)
            rows = result.fetchall()
            print(f"DEBUG: Found {len(rows)} analytics records for player_id {player_id} across multiple seasons")

            analytics = []
            for row in rows:
                analytics.append({
                    'week': row[0],
                    'season': row[1],
                    'ppr_points': row[2],
                    'snap_percentage': row[3],
                    'target_share': row[4],
                    'red_zone_share': row[5],
                    'points_per_snap': row[6],
                    'points_per_target': row[7],
                    'boom_rate': row[8],
                    'bust_rate': row[9],
                    'floor_score': row[10],
                    'ceiling_score': row[11],
                    'opponent': row[12],
                    'injury_designation': row[13],
                    'game_script': row[14],
                    'season_weight': row[15]
                })

            return analytics
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
        """Calculate usage trends over specified weeks with season weighting"""
        try:
            analytics = await self.get_player_analytics(player_id, weeks, season)

            if len(analytics) < 2:
                return {}

            # Calculate weighted trends for key metrics
            snap_data = [(a['snap_percentage'], a['season_weight']) for a in analytics if a['snap_percentage']]
            target_data = [(a['target_share'], a['season_weight']) for a in analytics if a['target_share']]
            red_zone_data = [(a['red_zone_share'], a['season_weight']) for a in analytics if a['red_zone_share']]

            trends = {}

            if snap_data:
                snap_values = [d[0] for d in snap_data]
                snap_weights = [d[1] for d in snap_data]
                trends['snap_share_trend'] = self._calculate_trend(snap_values)
                trends['avg_snap_share'] = self._calculate_weighted_average(snap_values, snap_weights)
                trends['snap_share_consistency'] = statistics.stdev(snap_values) if len(snap_values) > 1 else 0

            if target_data:
                target_values = [d[0] for d in target_data]
                target_weights = [d[1] for d in target_data]
                trends['target_share_trend'] = self._calculate_trend(target_values)
                trends['avg_target_share'] = self._calculate_weighted_average(target_values, target_weights)
                trends['target_share_consistency'] = statistics.stdev(target_values) if len(target_values) > 1 else 0

            if red_zone_data:
                rz_values = [d[0] for d in red_zone_data]
                rz_weights = [d[1] for d in red_zone_data]
                trends['red_zone_usage_trend'] = self._calculate_trend(rz_values)
                trends['avg_red_zone_share'] = self._calculate_weighted_average(rz_values, rz_weights)

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
        """Calculate advanced efficiency metrics with season weighting"""
        try:
            analytics = await self.get_player_analytics(player_id, weeks, season)

            if not analytics:
                return {}

            # Calculate weighted efficiency metrics
            efficiency_data = {
                'points_per_snap': [],
                'points_per_target': [],
                'points_per_touch': [],
                'red_zone_efficiency': []
            }

            for week_data in analytics:
                weight = week_data.get('season_weight', 1.0)
                if week_data.get('points_per_snap'):
                    efficiency_data['points_per_snap'].append((week_data['points_per_snap'], weight))
                if week_data.get('points_per_target'):
                    efficiency_data['points_per_target'].append((week_data['points_per_target'], weight))
                if week_data.get('points_per_touch'):
                    efficiency_data['points_per_touch'].append((week_data['points_per_touch'], weight))
                if week_data.get('red_zone_efficiency'):
                    efficiency_data['red_zone_efficiency'].append((week_data['red_zone_efficiency'], weight))

            # Calculate weighted averages and trends
            result = {}
            for metric, data_points in efficiency_data.items():
                if data_points:
                    values = [d[0] for d in data_points]
                    weights = [d[1] for d in data_points]
                    result[f'avg_{metric}'] = self._calculate_weighted_average(values, weights)
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
    
    def _calculate_weighted_average(self, values: List[float], weights: List[float]) -> float:
        """Calculate weighted average with season weights"""
        if not values or not weights or len(values) != len(weights):
            return 0

        total_weighted_sum = sum(value * weight for value, weight in zip(values, weights))
        total_weights = sum(weights)

        if total_weights == 0:
            return 0

        return round(total_weighted_sum / total_weights, 2)

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