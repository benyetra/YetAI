"""
Betting Analytics Service
Provides comprehensive analytics based on real user betting data
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, desc, case
from app.core.database import SessionLocal
from app.models.database_models import User, Bet, ParlayBet, Game
# from app.lib.formatting import formatSpread, formatTotal, formatGameStatus

logger = logging.getLogger(__name__)

class BettingAnalyticsService:
    """Analyzes user betting performance using real database data"""
    
    def __init__(self):
        pass
    
    async def get_user_performance_analytics(self, user_id: int, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive user betting performance analytics"""
        try:
            db = SessionLocal()
            try:
                cutoff_date = datetime.now() - timedelta(days=days)
                
                # Get all user bets in the time period
                user_bets = db.query(Bet).filter(
                    and_(
                        Bet.user_id == user_id,
                        Bet.placed_at >= cutoff_date
                    )
                ).all()
                
                # Get parlay bets
                parlay_bets = db.query(ParlayBet).filter(
                    and_(
                        ParlayBet.user_id == user_id,
                        ParlayBet.placed_at >= cutoff_date
                    )
                ).all()
                
                # Calculate overall statistics
                total_bets = len(user_bets) + len(parlay_bets)
                total_amount_wagered = sum(bet.amount for bet in user_bets) + sum(bet.amount for bet in parlay_bets)
                
                # Calculate wins, losses, and profits
                won_bets = [bet for bet in user_bets if bet.status == 'won']
                lost_bets = [bet for bet in user_bets if bet.status == 'lost']
                pending_bets = [bet for bet in user_bets if bet.status == 'pending']
                
                won_parlays = [bet for bet in parlay_bets if bet.status == 'won']
                lost_parlays = [bet for bet in parlay_bets if bet.status == 'lost']
                pending_parlays = [bet for bet in parlay_bets if bet.status == 'pending']
                
                total_won = len(won_bets) + len(won_parlays)
                total_lost = len(lost_bets) + len(lost_parlays)
                total_pending = len(pending_bets) + len(pending_parlays)
                
                # Calculate profit/loss
                straight_bet_profit = sum(bet.potential_win - bet.amount if bet.status == 'won' else -bet.amount if bet.status == 'lost' else 0 for bet in user_bets)
                parlay_profit = sum(bet.potential_win - bet.amount if bet.status == 'won' else -bet.amount if bet.status == 'lost' else 0 for bet in parlay_bets)
                total_profit = straight_bet_profit + parlay_profit
                
                # Calculate win rate
                resolved_bets = total_won + total_lost
                win_rate = (total_won / resolved_bets * 100) if resolved_bets > 0 else 0
                
                # Calculate ROI
                roi = (total_profit / total_amount_wagered * 100) if total_amount_wagered > 0 else 0
                
                # Get sport breakdown
                sport_stats = await self._get_sport_breakdown(user_id, cutoff_date, db)
                
                # Get bet type breakdown
                bet_type_stats = await self._get_bet_type_breakdown(user_id, cutoff_date, db)
                
                # Get recent performance trend (last 7 days vs previous period)
                recent_trend = await self._get_performance_trend(user_id, db)
                
                return {
                    "status": "success",
                    "period_days": days,
                    "overview": {
                        "total_bets": total_bets,
                        "total_wagered": round(total_amount_wagered, 2),
                        "total_profit": round(total_profit, 2),
                        "win_rate": round(win_rate, 1),
                        "roi": round(roi, 1),
                        "won_bets": total_won,
                        "lost_bets": total_lost,
                        "pending_bets": total_pending
                    },
                    "sport_breakdown": sport_stats,
                    "bet_type_breakdown": bet_type_stats,
                    "performance_trend": recent_trend,
                    "insights": await self._generate_insights(user_bets, parlay_bets, sport_stats, bet_type_stats)
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting user performance analytics: {e}")
            return {"status": "error", "message": str(e)}
    
    async def _get_sport_breakdown(self, user_id: int, cutoff_date: datetime, db: Session) -> List[Dict]:
        """Get betting performance broken down by sport"""
        try:
            # Get bets with sport information
            sport_query = db.query(
                Bet.sport,
                func.count(Bet.id).label('total_bets'),
                func.sum(Bet.amount).label('total_wagered'),
                func.sum(case(
                    (Bet.status == 'won', Bet.potential_win - Bet.amount),
                    (Bet.status == 'lost', -Bet.amount),
                    else_=0
                )).label('profit_loss'),
                func.sum(case(
                    (Bet.status == 'won', 1),
                    else_=0
                )).label('wins'),
                func.sum(case(
                    (and_(Bet.status == 'won'), 1),
                    (and_(Bet.status == 'lost'), 1),
                    else_=0
                )).label('resolved')
            ).filter(
                and_(
                    Bet.user_id == user_id,
                    Bet.placed_at >= cutoff_date
                )
            ).group_by(Bet.sport).all()
            
            sport_stats = []
            for stat in sport_query:
                win_rate = (stat.wins / stat.resolved * 100) if stat.resolved > 0 else 0
                roi = (stat.profit_loss / stat.total_wagered * 100) if stat.total_wagered > 0 else 0
                
                sport_stats.append({
                    "sport": stat.sport,
                    "sport_name": self._format_sport_name(stat.sport),
                    "total_bets": stat.total_bets,
                    "total_wagered": round(float(stat.total_wagered or 0), 2),
                    "profit_loss": round(float(stat.profit_loss or 0), 2),
                    "win_rate": round(win_rate, 1),
                    "roi": round(roi, 1)
                })
            
            # Sort by profit/loss descending
            sport_stats.sort(key=lambda x: x['profit_loss'], reverse=True)
            return sport_stats
            
        except Exception as e:
            logger.error(f"Error getting sport breakdown: {e}")
            return []
    
    async def _get_bet_type_breakdown(self, user_id: int, cutoff_date: datetime, db: Session) -> List[Dict]:
        """Get betting performance broken down by bet type"""
        try:
            bet_type_query = db.query(
                Bet.bet_type,
                func.count(Bet.id).label('total_bets'),
                func.sum(Bet.amount).label('total_wagered'),
                func.sum(case(
                    (Bet.status == 'won', Bet.potential_win - Bet.amount),
                    (Bet.status == 'lost', -Bet.amount),
                    else_=0
                )).label('profit_loss'),
                func.sum(case(
                    (Bet.status == 'won', 1),
                    else_=0
                )).label('wins'),
                func.sum(case(
                    (and_(Bet.status == 'won'), 1),
                    (and_(Bet.status == 'lost'), 1),
                    else_=0
                )).label('resolved')
            ).filter(
                and_(
                    Bet.user_id == user_id,
                    Bet.placed_at >= cutoff_date
                )
            ).group_by(Bet.bet_type).all()
            
            bet_type_stats = []
            for stat in bet_type_query:
                win_rate = (stat.wins / stat.resolved * 100) if stat.resolved > 0 else 0
                roi = (stat.profit_loss / stat.total_wagered * 100) if stat.total_wagered > 0 else 0
                
                bet_type_stats.append({
                    "bet_type": stat.bet_type,
                    "bet_type_name": self._format_bet_type_name(stat.bet_type),
                    "total_bets": stat.total_bets,
                    "total_wagered": round(float(stat.total_wagered or 0), 2),
                    "profit_loss": round(float(stat.profit_loss or 0), 2),
                    "win_rate": round(win_rate, 1),
                    "roi": round(roi, 1)
                })
            
            # Sort by total bets descending
            bet_type_stats.sort(key=lambda x: x['total_bets'], reverse=True)
            return bet_type_stats
            
        except Exception as e:
            logger.error(f"Error getting bet type breakdown: {e}")
            return []
    
    async def _get_performance_trend(self, user_id: int, db: Session) -> Dict:
        """Get performance trend comparison (last 7 days vs previous 7 days)"""
        try:
            now = datetime.now()
            last_7_days = now - timedelta(days=7)
            previous_7_days = now - timedelta(days=14)
            
            # Last 7 days performance
            recent_bets = db.query(Bet).filter(
                and_(
                    Bet.user_id == user_id,
                    Bet.placed_at >= last_7_days
                )
            ).all()
            
            # Previous 7 days performance
            previous_bets = db.query(Bet).filter(
                and_(
                    Bet.user_id == user_id,
                    Bet.placed_at >= previous_7_days,
                    Bet.placed_at < last_7_days
                )
            ).all()
            
            def calculate_metrics(bets):
                if not bets:
                    return {"win_rate": 0, "profit": 0, "total_bets": 0}
                
                won = len([b for b in bets if b.status == 'won'])
                lost = len([b for b in bets if b.status == 'lost'])
                resolved = won + lost
                
                win_rate = (won / resolved * 100) if resolved > 0 else 0
                profit = sum(b.potential_win - b.amount if b.status == 'won' else -b.amount if b.status == 'lost' else 0 for b in bets)
                
                return {
                    "win_rate": round(win_rate, 1),
                    "profit": round(profit, 2),
                    "total_bets": len(bets)
                }
            
            recent_metrics = calculate_metrics(recent_bets)
            previous_metrics = calculate_metrics(previous_bets)
            
            # Calculate trends
            win_rate_trend = recent_metrics["win_rate"] - previous_metrics["win_rate"]
            profit_trend = recent_metrics["profit"] - previous_metrics["profit"]
            
            return {
                "recent_period": recent_metrics,
                "previous_period": previous_metrics,
                "win_rate_change": round(win_rate_trend, 1),
                "profit_change": round(profit_trend, 2),
                "trend_direction": "improving" if win_rate_trend > 0 else "declining" if win_rate_trend < 0 else "stable"
            }
            
        except Exception as e:
            logger.error(f"Error getting performance trend: {e}")
            return {}
    
    async def _generate_insights(self, user_bets: List, parlay_bets: List, sport_stats: List, bet_type_stats: List) -> List[Dict]:
        """Generate actionable insights based on betting patterns"""
        insights = []
        
        try:
            # Best performing sport insight
            if sport_stats:
                best_sport = max(sport_stats, key=lambda x: x['roi'])
                if best_sport['roi'] > 0:
                    insights.append({
                        "type": "positive",
                        "icon": "trending-up",
                        "message": f"Your {best_sport['sport_name']} betting shows strong ROI of {best_sport['roi']}%"
                    })
            
            # Best bet type insight
            if bet_type_stats:
                best_bet_type = max(bet_type_stats, key=lambda x: x['win_rate'])
                if best_bet_type['win_rate'] > 60:
                    insights.append({
                        "type": "positive", 
                        "icon": "target",
                        "message": f"Strong performance on {best_bet_type['bet_type_name']} bets ({best_bet_type['win_rate']}% win rate)"
                    })
            
            # Warning for poor performance
            if sport_stats:
                worst_sport = min(sport_stats, key=lambda x: x['roi'])
                if worst_sport['roi'] < -10 and worst_sport['total_bets'] >= 5:
                    insights.append({
                        "type": "warning",
                        "icon": "trending-down", 
                        "message": f"Consider reducing bet sizes on {worst_sport['sport_name']} (ROI: {worst_sport['roi']}%)"
                    })
            
            # Parlay vs straight bet insight
            total_straight_bets = len(user_bets)
            total_parlays = len(parlay_bets)
            
            if total_parlays > total_straight_bets:
                insights.append({
                    "type": "info",
                    "icon": "info",
                    "message": "You bet more parlays than straight bets. Consider mixing in more single bets for consistent profits."
                })
            
            return insights
            
        except Exception as e:
            logger.error(f"Error generating insights: {e}")
            return []
    
    def _format_sport_name(self, sport_key: str) -> str:
        """Format sport key to readable name"""
        sport_mapping = {
            'americanfootball_nfl': 'NFL',
            'basketball_nba': 'NBA', 
            'baseball_mlb': 'MLB',
            'icehockey_nhl': 'NHL',
            'soccer_epl': 'Premier League',
            'basketball_ncaab': 'College Basketball',
            'americanfootball_ncaaf': 'College Football',
            'basketball_wnba': 'WNBA'
        }
        return sport_mapping.get(sport_key, sport_key.replace('_', ' ').title())
    
    def _format_bet_type_name(self, bet_type: str) -> str:
        """Format bet type to readable name"""
        bet_type_mapping = {
            'moneyline': 'Moneyline',
            'spread': 'Point Spread', 
            'total': 'Over/Under',
            'player_prop': 'Player Props',
            'team_prop': 'Team Props'
        }
        return bet_type_mapping.get(bet_type, bet_type.replace('_', ' ').title())

# Global instance
betting_analytics_service = BettingAnalyticsService()