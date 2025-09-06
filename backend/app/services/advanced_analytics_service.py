"""
Advanced Analytics Service - Real-time 2025 performance vs historical baselines
"""
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc
from datetime import datetime, timedelta
import logging
import numpy as np
from scipy import stats
from collections import defaultdict

from app.models.fantasy_models import (
    FantasyPlayer, PlayerAnalytics, PlayerTrends, PlayerValue,
    FantasyLeague, FantasyTeam, TeamNeedsAnalysis,
    PlayerProjection, FantasyPosition
)

logger = logging.getLogger(__name__)

class AdvancedAnalyticsService:
    """
    Advanced analytics that compares current season performance to historical baselines
    Key features:
    - Performance vs Expectation (PvE) scoring
    - Trend detection with statistical significance
    - Trade value calculations based on ROS (Rest of Season) projections
    - Team construction analysis
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.current_season = 2025
        self.current_week = self._get_current_week()
        
    def _get_current_week(self) -> int:
        """Get the most recent week with data in current season"""
        latest = self.db.query(func.max(PlayerAnalytics.week)).filter(
            PlayerAnalytics.season == self.current_season
        ).scalar()
        return latest if latest else 0
    
    def get_performance_vs_expectation(self, player_id: int) -> Dict[str, Any]:
        """
        Compare 2025 performance to historical baseline
        Identifies breakouts, busts, and trajectory changes
        """
        try:
            # Get historical baseline (2021-2024)
            historical = self.db.query(
                func.avg(PlayerAnalytics.ppr_points).label('avg_points'),
                func.stddev(PlayerAnalytics.ppr_points).label('std_dev'),
                func.percentile_cont(0.5).within_group(PlayerAnalytics.ppr_points).label('median'),
                func.percentile_cont(0.25).within_group(PlayerAnalytics.ppr_points).label('q1'),
                func.percentile_cont(0.75).within_group(PlayerAnalytics.ppr_points).label('q3'),
                func.avg(PlayerAnalytics.targets).label('avg_targets'),
                func.avg(PlayerAnalytics.carries).label('avg_carries'),
                func.avg(PlayerAnalytics.snap_percentage).label('avg_snaps')
            ).filter(
                and_(
                    PlayerAnalytics.player_id == player_id,
                    PlayerAnalytics.season.between(2021, 2024)
                )
            ).first()
            
            # Get 2025 performance
            current_season = self.db.query(
                func.avg(PlayerAnalytics.ppr_points).label('avg_points'),
                func.stddev(PlayerAnalytics.ppr_points).label('std_dev'),
                func.count(PlayerAnalytics.id).label('games'),
                func.avg(PlayerAnalytics.targets).label('avg_targets'),
                func.avg(PlayerAnalytics.carries).label('avg_carries'),
                func.avg(PlayerAnalytics.snap_percentage).label('avg_snaps')
            ).filter(
                and_(
                    PlayerAnalytics.player_id == player_id,
                    PlayerAnalytics.season == self.current_season
                )
            ).first()
            
            if not historical or not current_season or current_season.games == 0:
                return {"error": "Insufficient data"}
            
            # Calculate Performance vs Expectation score
            if historical.std_dev and historical.std_dev > 0:
                z_score = (current_season.avg_points - historical.avg_points) / historical.std_dev
                pve_score = 50 + (z_score * 10)  # Normalize to 0-100 scale
            else:
                pve_score = 50
            
            # Determine performance category
            if pve_score >= 65:
                category = "EXCEEDING"
                trend = "📈"
            elif pve_score >= 55:
                category = "ABOVE"
                trend = "🔺"
            elif pve_score >= 45:
                category = "MEETING"
                trend = "➡️"
            elif pve_score >= 35:
                category = "BELOW"
                trend = "🔻"
            else:
                category = "UNDERPERFORMING"
                trend = "📉"
            
            # Calculate usage changes
            usage_change = {
                "targets": self._calculate_change(historical.avg_targets, current_season.avg_targets),
                "carries": self._calculate_change(historical.avg_carries, current_season.avg_carries),
                "snaps": self._calculate_change(historical.avg_snaps, current_season.avg_snaps)
            }
            
            # Statistical significance test
            if current_season.games >= 3:
                # Get individual game data for t-test
                historical_games = self.db.query(PlayerAnalytics.ppr_points).filter(
                    and_(
                        PlayerAnalytics.player_id == player_id,
                        PlayerAnalytics.season.between(2021, 2024)
                    )
                ).all()
                
                current_games = self.db.query(PlayerAnalytics.ppr_points).filter(
                    and_(
                        PlayerAnalytics.player_id == player_id,
                        PlayerAnalytics.season == self.current_season
                    )
                ).all()
                
                if len(historical_games) > 10 and len(current_games) >= 3:
                    hist_values = [g[0] for g in historical_games]
                    curr_values = [g[0] for g in current_games]
                    t_stat, p_value = stats.ttest_ind(curr_values, hist_values)
                    significant = p_value < 0.05
                else:
                    p_value = None
                    significant = False
            else:
                p_value = None
                significant = False
            
            # Get player info
            player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
            
            return {
                "player_id": player_id,
                "player_name": player.name if player else "Unknown",
                "position": player.position if player else "Unknown",
                "pve_score": round(pve_score, 1),
                "category": category,
                "trend": trend,
                "current_season": {
                    "games": current_season.games,
                    "avg_points": round(current_season.avg_points, 1) if current_season.avg_points else 0,
                    "consistency": round(current_season.std_dev, 1) if current_season.std_dev else 0
                },
                "historical_baseline": {
                    "avg_points": round(historical.avg_points, 1) if historical.avg_points else 0,
                    "median": round(historical.median, 1) if historical.median else 0,
                    "q1": round(historical.q1, 1) if historical.q1 else 0,
                    "q3": round(historical.q3, 1) if historical.q3 else 0
                },
                "usage_changes": usage_change,
                "statistical_significance": {
                    "significant": significant,
                    "p_value": round(p_value, 4) if p_value else None,
                    "sample_size": current_season.games
                },
                "recommendation": self._generate_recommendation(pve_score, usage_change, significant)
            }
            
        except Exception as e:
            logger.error(f"Error in performance vs expectation: {str(e)}")
            return {"error": str(e)}
    
    def calculate_dynamic_trade_value(self, player_id: int) -> Dict[str, Any]:
        """
        Calculate trade value based on:
        - Current season performance trajectory
        - Historical reliability
        - Rest of season schedule
        - Positional scarcity
        """
        try:
            # Get PvE analysis
            pve = self.get_performance_vs_expectation(player_id)
            
            # Get historical consistency
            historical_consistency = self.db.query(
                func.count(PlayerAnalytics.id).label('games'),
                func.avg(PlayerAnalytics.ppr_points).label('avg_points'),
                func.stddev(PlayerAnalytics.ppr_points).label('std_dev')
            ).filter(
                and_(
                    PlayerAnalytics.player_id == player_id,
                    PlayerAnalytics.season.between(2021, 2024),
                    PlayerAnalytics.ppr_points > 0
                )
            ).first()
            
            # Calculate base value (0-100)
            base_value = 50
            
            # Adjust for current performance
            if pve.get('pve_score'):
                performance_adjustment = (pve['pve_score'] - 50) * 0.4
                base_value += performance_adjustment
            
            # Adjust for consistency
            if historical_consistency and historical_consistency.std_dev:
                cv = historical_consistency.std_dev / historical_consistency.avg_points if historical_consistency.avg_points > 0 else 1
                consistency_bonus = max(-10, min(10, (0.4 - cv) * 20))
                base_value += consistency_bonus
            
            # Positional scarcity adjustment
            player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
            if player:
                position_value = self._get_positional_scarcity_value(player.position)
                base_value *= position_value
            
            # Recent form multiplier
            recent_games = self.db.query(PlayerAnalytics).filter(
                and_(
                    PlayerAnalytics.player_id == player_id,
                    PlayerAnalytics.season == self.current_season
                )
            ).order_by(PlayerAnalytics.week.desc()).limit(3).all()
            
            if recent_games:
                recent_avg = np.mean([g.ppr_points for g in recent_games])
                if historical_consistency and historical_consistency.avg_points > 0:
                    form_multiplier = recent_avg / historical_consistency.avg_points
                    form_adjustment = (form_multiplier - 1) * 10
                    base_value += max(-15, min(15, form_adjustment))
            
            # Normalize to 0-100
            trade_value = max(0, min(100, base_value))
            
            # Determine trade tier
            if trade_value >= 85:
                tier = "ELITE"
                action = "HOLD/BUY"
            elif trade_value >= 70:
                tier = "HIGH"
                action = "BUY"
            elif trade_value >= 55:
                tier = "MEDIUM"
                action = "HOLD"
            elif trade_value >= 40:
                tier = "LOW"
                action = "SELL"
            else:
                tier = "SELL_NOW"
                action = "SELL"
            
            return {
                "player_id": player_id,
                "player_name": player.name if player else "Unknown",
                "position": player.position if player else "Unknown",
                "trade_value": round(trade_value, 1),
                "tier": tier,
                "recommended_action": action,
                "value_factors": {
                    "performance_trend": pve.get('category', 'UNKNOWN'),
                    "consistency_rating": "HIGH" if historical_consistency and historical_consistency.std_dev < 7 else "MEDIUM" if historical_consistency and historical_consistency.std_dev < 10 else "LOW",
                    "recent_form": "HOT" if recent_games and recent_avg > historical_consistency.avg_points * 1.2 else "COLD" if recent_games and recent_avg < historical_consistency.avg_points * 0.8 else "STABLE",
                    "games_played_2025": pve.get('current_season', {}).get('games', 0)
                },
                "comparable_players": self._find_comparable_players(player_id, trade_value)
            }
            
        except Exception as e:
            logger.error(f"Error calculating trade value: {str(e)}")
            return {"error": str(e)}
    
    def get_team_construction_analysis(self, team_id: int) -> Dict[str, Any]:
        """
        Analyze team construction using 2025 performance data
        Identifies strengths, weaknesses, and optimization opportunities
        """
        try:
            # Get team roster
            team = self.db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
            if not team:
                return {"error": "Team not found"}
            
            # Analyze each roster position
            roster_analysis = []
            total_pve = 0
            position_counts = defaultdict(int)
            
            for spot in team.roster_spots:
                if spot.player_id:
                    pve = self.get_performance_vs_expectation(spot.player_id)
                    trade_value = self.calculate_dynamic_trade_value(spot.player_id)
                    
                    roster_analysis.append({
                        "position": spot.position,
                        "player_id": spot.player_id,
                        "player_name": spot.player.name if spot.player else "Unknown",
                        "pve_score": pve.get('pve_score', 50),
                        "trade_value": trade_value.get('trade_value', 50),
                        "trend": pve.get('trend', '➡️')
                    })
                    
                    total_pve += pve.get('pve_score', 50)
                    position_counts[spot.position] += 1
            
            # Calculate team metrics
            avg_pve = total_pve / len(roster_analysis) if roster_analysis else 50
            
            # Identify strengths and weaknesses
            strengths = [p for p in roster_analysis if p['pve_score'] >= 60]
            weaknesses = [p for p in roster_analysis if p['pve_score'] <= 40]
            
            # Generate optimization recommendations
            recommendations = []
            
            # Check for sell-high candidates
            sell_high = [p for p in roster_analysis if p['pve_score'] > 70 and p['trade_value'] > 80]
            if sell_high:
                recommendations.append({
                    "type": "SELL_HIGH",
                    "players": [p['player_name'] for p in sell_high],
                    "reason": "Peak value - consider trading for depth or future assets"
                })
            
            # Check for buy-low targets in weaknesses
            if weaknesses:
                recommendations.append({
                    "type": "UPGRADE_NEEDED",
                    "positions": list(set([p['position'] for p in weaknesses])),
                    "reason": "Underperforming positions that need immediate attention"
                })
            
            # Position group analysis
            position_analysis = {}
            for pos in ['QB', 'RB', 'WR', 'TE']:
                pos_players = [p for p in roster_analysis if p['position'] == pos]
                if pos_players:
                    position_analysis[pos] = {
                        "count": len(pos_players),
                        "avg_pve": np.mean([p['pve_score'] for p in pos_players]),
                        "avg_value": np.mean([p['trade_value'] for p in pos_players]),
                        "rating": self._rate_position_group([p['pve_score'] for p in pos_players])
                    }
            
            return {
                "team_id": team_id,
                "team_name": team.team_name,
                "overall_rating": self._calculate_team_rating(avg_pve),
                "avg_pve_score": round(avg_pve, 1),
                "roster_analysis": roster_analysis,
                "position_groups": position_analysis,
                "strengths": strengths,
                "weaknesses": weaknesses,
                "recommendations": recommendations,
                "championship_probability": self._estimate_championship_probability(avg_pve, position_analysis)
            }
            
        except Exception as e:
            logger.error(f"Error in team analysis: {str(e)}")
            return {"error": str(e)}
    
    def get_player_comparison(self, player_ids: List[int]) -> Dict[str, Any]:
        """
        Advanced player comparison using 2025 data vs historical baselines
        """
        try:
            comparisons = []
            
            for player_id in player_ids[:5]:  # Limit to 5 players
                pve = self.get_performance_vs_expectation(player_id)
                trade_value = self.calculate_dynamic_trade_value(player_id)
                
                # Get recent trending
                recent_games = self.db.query(
                    func.avg(PlayerAnalytics.ppr_points).label('avg_points')
                ).filter(
                    and_(
                        PlayerAnalytics.player_id == player_id,
                        PlayerAnalytics.season == self.current_season
                    )
                ).order_by(PlayerAnalytics.week.desc()).limit(3).scalar()
                
                # Get season totals
                season_stats = self.db.query(
                    func.sum(PlayerAnalytics.ppr_points).label('total_points'),
                    func.sum(PlayerAnalytics.touchdowns).label('total_tds'),
                    func.avg(PlayerAnalytics.targets).label('avg_targets')
                ).filter(
                    and_(
                        PlayerAnalytics.player_id == player_id,
                        PlayerAnalytics.season == self.current_season
                    )
                ).first()
                
                player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
                
                comparisons.append({
                    "player_id": player_id,
                    "player_name": player.name if player else "Unknown",
                    "position": player.position if player else "Unknown",
                    "team": player.team if player else "Unknown",
                    "pve_score": pve.get('pve_score', 50),
                    "trade_value": trade_value.get('trade_value', 50),
                    "trend": pve.get('trend', '➡️'),
                    "recent_ppg": round(recent_games, 1) if recent_games else 0,
                    "season_total": round(season_stats.total_points, 1) if season_stats and season_stats.total_points else 0,
                    "total_tds": season_stats.total_tds if season_stats else 0,
                    "usage": round(season_stats.avg_targets, 1) if season_stats and season_stats.avg_targets else 0,
                    "recommendation": trade_value.get('recommended_action', 'HOLD')
                })
            
            # Sort by trade value
            comparisons.sort(key=lambda x: x['trade_value'], reverse=True)
            
            # Generate head-to-head insights
            if len(comparisons) >= 2:
                insights = []
                best = comparisons[0]
                
                for comp in comparisons[1:]:
                    diff = best['trade_value'] - comp['trade_value']
                    if diff > 20:
                        insights.append(f"{best['player_name']} is significantly more valuable than {comp['player_name']}")
                    elif diff > 10:
                        insights.append(f"{best['player_name']} has moderate edge over {comp['player_name']}")
                    else:
                        insights.append(f"{best['player_name']} and {comp['player_name']} have similar value")
            else:
                insights = []
            
            return {
                "players": comparisons,
                "best_value": comparisons[0] if comparisons else None,
                "insights": insights,
                "trade_recommendations": self._generate_trade_recommendations(comparisons)
            }
            
        except Exception as e:
            logger.error(f"Error in player comparison: {str(e)}")
            return {"error": str(e)}
    
    def _calculate_change(self, historical: float, current: float) -> float:
        """Calculate percentage change"""
        if not historical or historical == 0:
            return 0
        return round(((current - historical) / historical) * 100, 1)
    
    def _generate_recommendation(self, pve_score: float, usage: Dict, significant: bool) -> str:
        """Generate actionable recommendation based on analysis"""
        if pve_score >= 70:
            if usage['targets'] > 20 or usage['carries'] > 20:
                return "STRONG BUY - Elite performance with increased usage"
            return "BUY - Exceeding expectations significantly"
        elif pve_score >= 60:
            if significant:
                return "BUY - Statistically significant improvement"
            return "HOLD - Performing above expectations"
        elif pve_score >= 40:
            return "HOLD - Meeting expectations"
        elif pve_score >= 30:
            if usage['snaps'] < -20:
                return "SELL - Declining usage and underperforming"
            return "MONITOR - Below expectations, watch for improvement"
        else:
            return "SELL - Significantly underperforming"
    
    def _get_positional_scarcity_value(self, position: str) -> float:
        """Get position scarcity multiplier"""
        scarcity = {
            'QB': 0.9,  # Less scarce
            'RB': 1.1,  # More scarce
            'WR': 1.0,  # Neutral
            'TE': 1.15  # Most scarce for elite players
        }
        return scarcity.get(position, 1.0)
    
    def _find_comparable_players(self, player_id: int, trade_value: float) -> List[Dict]:
        """Find players with similar trade value"""
        # This would query for players with similar trade values
        # Simplified for now
        return []
    
    def _rate_position_group(self, pve_scores: List[float]) -> str:
        """Rate a position group based on PvE scores"""
        avg = np.mean(pve_scores)
        if avg >= 60:
            return "ELITE"
        elif avg >= 52:
            return "STRONG"
        elif avg >= 48:
            return "AVERAGE"
        elif avg >= 40:
            return "WEAK"
        else:
            return "POOR"
    
    def _calculate_team_rating(self, avg_pve: float) -> str:
        """Calculate overall team rating"""
        if avg_pve >= 58:
            return "CHAMPIONSHIP CONTENDER"
        elif avg_pve >= 52:
            return "PLAYOFF TEAM"
        elif avg_pve >= 48:
            return "COMPETITIVE"
        elif avg_pve >= 44:
            return "STRUGGLING"
        else:
            return "REBUILDING"
    
    def _estimate_championship_probability(self, avg_pve: float, position_analysis: Dict) -> float:
        """Estimate championship probability based on team metrics"""
        base_prob = (avg_pve - 40) * 2  # Convert PvE to probability
        
        # Adjust for position group strength
        if position_analysis:
            rb_bonus = 5 if position_analysis.get('RB', {}).get('rating') in ['ELITE', 'STRONG'] else 0
            wr_bonus = 5 if position_analysis.get('WR', {}).get('rating') in ['ELITE', 'STRONG'] else 0
            base_prob += rb_bonus + wr_bonus
        
        return max(0, min(100, base_prob))
    
    def _generate_trade_recommendations(self, comparisons: List[Dict]) -> List[str]:
        """Generate trade recommendations from player comparisons"""
        recs = []
        
        if not comparisons:
            return recs
        
        # Find buy candidates
        buy_candidates = [p for p in comparisons if p['pve_score'] > 55 and p['trade_value'] < 60]
        if buy_candidates:
            recs.append(f"BUY LOW: {', '.join([p['player_name'] for p in buy_candidates[:2]])}")
        
        # Find sell candidates
        sell_candidates = [p for p in comparisons if p['pve_score'] < 45 and p['trade_value'] > 50]
        if sell_candidates:
            recs.append(f"SELL HIGH: {', '.join([p['player_name'] for p in sell_candidates[:2]])}")
        
        return recs