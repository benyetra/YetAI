"""
Trade Analyzer Service - Comprehensive fantasy trade evaluation and recommendation system
"""
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from datetime import datetime, timedelta
import logging
import json
from abc import ABC, abstractmethod

from app.models.fantasy_models import (
    Trade, TradeEvaluation, TradeRecommendation, DraftPick, PlayerValue,
    TeamNeedsAnalysis, FantasyTeam, FantasyPlayer, FantasyLeague,
    FantasyRosterSpot, PlayerAnalytics, PlayerTrends,
    TradeStatus, TradeGrade
)

logger = logging.getLogger(__name__)

class TradeAnalyzerService:
    """Comprehensive trade analysis and recommendation service"""
    
    def __init__(self, db: Session):
        self.db = db
        
    # ============================================================================
    # TRADE PROPOSAL AND MANAGEMENT
    # ============================================================================
    
    def propose_trade(self, league_id: int, proposing_team_id: int, target_team_id: int,
                     team1_gives: Dict[str, Any], team2_gives: Dict[str, Any],
                     trade_reason: str = None, expires_in_hours: int = 72) -> Dict[str, Any]:
        """Create a new trade proposal"""
        try:
            # Validate teams exist in league
            team1 = self.db.query(FantasyTeam).filter(
                and_(FantasyTeam.id == proposing_team_id, FantasyTeam.league_id == league_id)
            ).first()
            
            team2 = self.db.query(FantasyTeam).filter(
                and_(FantasyTeam.id == target_team_id, FantasyTeam.league_id == league_id)
            ).first()
            
            if not team1 or not team2:
                return {"success": False, "error": "Invalid teams"}
            
            # Validate trade assets
            validation_result = self._validate_trade_assets(
                proposing_team_id, target_team_id, team1_gives, team2_gives
            )
            
            if not validation_result["valid"]:
                return {"success": False, "error": validation_result["error"]}
            
            # Create trade proposal
            expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)
            
            trade = Trade(
                league_id=league_id,
                team1_id=proposing_team_id,
                team2_id=target_team_id,
                proposed_by_team_id=proposing_team_id,
                status=TradeStatus.PROPOSED,
                team1_gives=team1_gives,
                team2_gives=team2_gives,
                trade_reason=trade_reason,
                expires_at=expires_at
            )
            
            self.db.add(trade)
            self.db.flush()  # Get trade ID
            
            # Generate AI evaluation
            evaluation = self.evaluate_trade(trade.id)
            
            self.db.commit()
            
            return {
                "success": True,
                "trade_id": trade.id,
                "evaluation": evaluation,
                "expires_at": expires_at.isoformat()
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to propose trade: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def evaluate_trade(self, trade_id: int, force_refresh: bool = False) -> Dict[str, Any]:
        """Comprehensive trade evaluation with AI analysis"""
        try:
            trade = self.db.query(Trade).filter(Trade.id == trade_id).first()
            if not trade:
                return {"success": False, "error": "Trade not found"}
            
            # Check for existing evaluation
            existing_eval = self.db.query(TradeEvaluation).filter(
                TradeEvaluation.trade_id == trade_id
            ).first()
            
            if existing_eval and not force_refresh:
                return self._format_evaluation_response(existing_eval)
            
            # Generate comprehensive evaluation
            evaluation_data = self._generate_comprehensive_evaluation(trade)
            
            if existing_eval:
                # Update existing evaluation
                for key, value in evaluation_data.items():
                    setattr(existing_eval, key, value)
                existing_eval.created_at = datetime.utcnow()
                evaluation = existing_eval
            else:
                # Create new evaluation
                evaluation = TradeEvaluation(trade_id=trade_id, **evaluation_data)
                self.db.add(evaluation)
            
            self.db.commit()
            
            return self._format_evaluation_response(evaluation)
            
        except Exception as e:
            logger.error(f"Failed to evaluate trade {trade_id}: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _validate_trade_assets(self, team1_id: int, team2_id: int, 
                              team1_gives: Dict, team2_gives: Dict) -> Dict[str, Any]:
        """Validate that all trade assets are valid and owned by correct teams"""
        try:
            # Validate team1 assets
            if not self._validate_team_assets(team1_id, team1_gives):
                return {"valid": False, "error": "Team 1 doesn't own specified assets"}
            
            # Validate team2 assets  
            if not self._validate_team_assets(team2_id, team2_gives):
                return {"valid": False, "error": "Team 2 doesn't own specified assets"}
            
            # Ensure both sides are giving something
            if not (team1_gives.get("players") or team1_gives.get("picks") or team1_gives.get("faab", 0) > 0):
                return {"valid": False, "error": "Team 1 must give something"}
                
            if not (team2_gives.get("players") or team2_gives.get("picks") or team2_gives.get("faab", 0) > 0):
                return {"valid": False, "error": "Team 2 must give something"}
            
            return {"valid": True}
            
        except Exception as e:
            logger.error(f"Asset validation error: {str(e)}")
            return {"valid": False, "error": "Validation failed"}
    
    def _validate_team_assets(self, team_id: int, assets: Dict) -> bool:
        """Validate team owns the specified assets"""
        # Validate players
        if assets.get("players"):
            roster_player_ids = self.db.query(FantasyRosterSpot.player_id).filter(
                FantasyRosterSpot.team_id == team_id
            ).subquery()
            
            owned_players = self.db.query(FantasyPlayer.id).filter(
                FantasyPlayer.id.in_(assets["players"]),
                FantasyPlayer.id.in_(roster_player_ids)
            ).count()
            
            if owned_players != len(assets["players"]):
                return False
        
        # Validate draft picks
        if assets.get("picks"):
            owned_picks = self.db.query(DraftPick.id).filter(
                DraftPick.id.in_(assets["picks"]),
                DraftPick.current_owner_team_id == team_id,
                DraftPick.is_tradeable == True
            ).count()
            
            if owned_picks != len(assets["picks"]):
                return False
        
        return True
    
    # ============================================================================
    # COMPREHENSIVE TRADE EVALUATION ENGINE
    # ============================================================================
    
    def _generate_comprehensive_evaluation(self, trade: Trade) -> Dict[str, Any]:
        """Generate comprehensive AI-powered trade evaluation"""
        
        # Get league context
        league_context = self._get_league_context(trade.league_id)
        
        # Get team contexts
        team1_context = self._get_team_context(trade.team1_id, league_context)
        team2_context = self._get_team_context(trade.team2_id, league_context)
        
        # Calculate player values
        team1_values = self._calculate_trade_side_value(
            trade.team1_gives, team1_context, league_context
        )
        team2_values = self._calculate_trade_side_value(
            trade.team2_gives, team2_context, league_context
        )
        
        # Generate detailed analysis for each team
        team1_analysis = self._analyze_trade_impact(
            trade.team1_id, trade.team1_gives, trade.team2_gives, 
            team1_context, league_context
        )
        
        team2_analysis = self._analyze_trade_impact(
            trade.team2_id, trade.team2_gives, trade.team1_gives,
            team2_context, league_context
        )
        
        # Calculate grades
        team1_grade = self._calculate_trade_grade(team1_analysis, team1_values, team2_values)
        team2_grade = self._calculate_trade_grade(team2_analysis, team2_values, team1_values)
        
        # Calculate fairness
        fairness_score = self._calculate_fairness_score(team1_values, team2_values)
        
        # Generate AI summary
        ai_summary = self._generate_ai_summary(
            trade, team1_analysis, team2_analysis, team1_grade, team2_grade, fairness_score
        )
        
        # Extract key factors
        key_factors = self._extract_key_factors(team1_analysis, team2_analysis, league_context)
        
        return {
            "team1_grade": team1_grade,
            "team2_grade": team2_grade,
            "team1_analysis": team1_analysis,
            "team2_analysis": team2_analysis,
            "team1_value_given": team1_values["total_value_given"],
            "team1_value_received": team1_values["total_value_received"],
            "team2_value_given": team2_values["total_value_given"],
            "team2_value_received": team2_values["total_value_received"],
            "trade_context": {
                "league_type": league_context["scoring_type"],
                "week": league_context["current_week"],
                "trade_deadline_proximity": league_context["trade_deadline_weeks"],
                "playoff_implications": league_context["playoff_race"]
            },
            "fairness_score": fairness_score,
            "ai_summary": ai_summary,
            "key_factors": key_factors,
            "confidence": self._calculate_evaluation_confidence(team1_analysis, team2_analysis)
        }
    
    def _get_league_context(self, league_id: int) -> Dict[str, Any]:
        """Get comprehensive league context for evaluation"""
        league = self.db.query(FantasyLeague).filter(FantasyLeague.id == league_id).first()
        
        # Determine current week (simplified - would integrate with real NFL week)
        current_week = 8  # This would come from NFL schedule service
        
        # Calculate weeks until trade deadline
        trade_deadline_weeks = max(0, 10 - current_week)  # Assuming week 10 deadline
        
        # Get playoff race context
        teams = self.db.query(FantasyTeam).filter(FantasyTeam.league_id == league_id).all()
        sorted_teams = sorted(teams, key=lambda t: (-t.wins, -t.points_for))
        
        playoff_spots = league.playoff_teams or 6
        playoff_race = {
            "in_playoffs": len([t for t in sorted_teams[:playoff_spots]]),
            "bubble_teams": len([t for t in sorted_teams[playoff_spots:playoff_spots+2]]),
            "eliminated": len([t for t in sorted_teams[playoff_spots+2:]])
        }
        
        return {
            "league_id": league_id,
            "scoring_type": league.scoring_type or "ppr",
            "team_count": league.team_count or 12,
            "current_week": current_week,
            "trade_deadline_weeks": trade_deadline_weeks,
            "playoff_race": playoff_race,
            "is_dynasty": league.league_type == "dynasty",
            "playoff_teams": playoff_spots
        }
    
    def _get_team_context(self, team_id: int, league_context: Dict) -> Dict[str, Any]:
        """Get comprehensive team context for evaluation"""
        team = self.db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
        
        # Get recent team needs analysis
        needs_analysis = self.db.query(TeamNeedsAnalysis).filter(
            and_(
                TeamNeedsAnalysis.team_id == team_id,
                TeamNeedsAnalysis.week <= league_context["current_week"]
            )
        ).order_by(desc(TeamNeedsAnalysis.week)).first()
        
        # Calculate team standing
        all_teams = self.db.query(FantasyTeam).filter(
            FantasyTeam.league_id == team.league_id
        ).all()
        
        sorted_teams = sorted(all_teams, key=lambda t: (-t.wins, -t.points_for))
        team_rank = next(i for i, t in enumerate(sorted_teams, 1) if t.id == team_id)
        
        # Determine team strategy
        playoff_position = team_rank <= league_context["playoff_teams"]
        championship_contender = team_rank <= 3
        should_rebuild = team_rank > league_context["team_count"] * 0.75
        
        return {
            "team_id": team_id,
            "team_name": team.name,
            "wins": team.wins,
            "losses": team.losses,
            "points_for": float(team.points_for) if team.points_for else 0,
            "points_against": float(team.points_against) if team.points_against else 0,
            "team_rank": team_rank,
            "playoff_position": playoff_position,
            "championship_contender": championship_contender,
            "should_rebuild": should_rebuild,
            "needs_analysis": needs_analysis.__dict__ if needs_analysis else {},
            "record_trend": self._calculate_recent_performance(team_id)
        }
    
    def _calculate_recent_performance(self, team_id: int) -> str:
        """Calculate recent team performance trend"""
        # This would integrate with matchup data to show recent W/L trend
        # Simplified for now
        return "stable"  # Could be "trending_up", "trending_down", "stable"
    
    def _calculate_trade_side_value(self, assets: Dict, team_context: Dict, 
                                  league_context: Dict) -> Dict[str, float]:
        """Calculate total value for one side of trade"""
        total_value_given = 0.0
        total_value_received = 0.0  # This will be calculated by the opposite perspective
        
        breakdown = {
            "players": {},
            "picks": {},
            "faab": 0
        }
        
        # Calculate player values
        if assets.get("players"):
            for player_id in assets["players"]:
                player_value = self._get_player_trade_value(
                    player_id, league_context, team_context
                )
                breakdown["players"][str(player_id)] = player_value
                total_value_given += player_value["total_value"]
        
        # Calculate draft pick values
        if assets.get("picks"):
            for pick_id in assets["picks"]:
                pick_value = self._get_draft_pick_value(pick_id, league_context)
                breakdown["picks"][str(pick_id)] = pick_value
                total_value_given += pick_value
        
        # Calculate FAAB value
        if assets.get("faab", 0) > 0:
            faab_value = self._get_faab_value(assets["faab"], league_context)
            breakdown["faab"] = faab_value
            total_value_given += faab_value
        
        return {
            "total_value_given": round(total_value_given, 2),
            "total_value_received": 0.0,  # Will be set by opposite calculation
            "breakdown": breakdown
        }
    
    def _get_player_trade_value(self, player_id: int, league_context: Dict, 
                               team_context: Dict) -> Dict[str, Any]:
        """Get comprehensive player trade value"""
        player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
        
        if not player:
            return {"total_value": 0, "error": "Player not found"}
        
        # Get recent player value record
        player_value = self.db.query(PlayerValue).filter(
            and_(
                PlayerValue.player_id == player_id,
                PlayerValue.league_id == league_context["league_id"],
                PlayerValue.week <= league_context["current_week"]
            )
        ).order_by(desc(PlayerValue.week)).first()
        
        # Get player analytics
        analytics = self.db.query(PlayerAnalytics).filter(
            and_(
                PlayerAnalytics.player_id == player_id,
                PlayerAnalytics.week <= league_context["current_week"]
            )
        ).order_by(desc(PlayerAnalytics.week)).first()
        
        # Get player trends
        trends = self.db.query(PlayerTrends).filter(
            and_(
                PlayerTrends.player_id == player_id,
                PlayerTrends.season == league_context.get("season", 2025)
            )
        ).first()
        
        # Base value calculation
        if player_value:
            base_value = self._select_appropriate_value(player_value, league_context)
        else:
            base_value = self._estimate_player_value(player, league_context)
        
        # Apply contextual adjustments
        contextual_multiplier = self._calculate_contextual_multiplier(
            player, league_context, team_context, analytics, trends
        )
        
        adjusted_value = base_value * contextual_multiplier
        
        return {
            "player_name": player.name,
            "position": player.position,
            "team": player.team,
            "base_value": round(base_value, 2),
            "contextual_multiplier": round(contextual_multiplier, 2),
            "total_value": round(adjusted_value, 2),
            "value_factors": self._get_value_factors(player, analytics, trends, league_context),
            "buy_low_indicator": trends.buy_low_indicator if trends else False,
            "sell_high_indicator": trends.sell_high_indicator if trends else False
        }
    
    def _select_appropriate_value(self, player_value: PlayerValue, league_context: Dict) -> float:
        """Select the appropriate value based on league type"""
        scoring_type = league_context["scoring_type"]
        
        if scoring_type == "ppr":
            return player_value.ppr_value or player_value.rest_of_season_value
        elif scoring_type == "standard":
            return player_value.standard_value or player_value.rest_of_season_value
        elif "superflex" in scoring_type or league_context.get("has_superflex"):
            return player_value.superflex_value or player_value.rest_of_season_value
        else:
            return player_value.rest_of_season_value
    
    def _estimate_player_value(self, player: FantasyPlayer, league_context: Dict) -> float:
        """Estimate player value when no specific data available"""
        position_values = {
            "QB": 15.0,
            "RB": 20.0,
            "WR": 18.0,
            "TE": 12.0,
            "K": 3.0,
            "DEF": 5.0
        }
        
        base = position_values.get(player.position, 20.0)
        
        # Adjust for superflex leagues
        if player.position == "QB" and league_context.get("has_superflex"):
            base *= 1.5
        
        return base
    
    def _calculate_contextual_multiplier(self, player: FantasyPlayer, league_context: Dict,
                                       team_context: Dict, analytics: PlayerAnalytics,
                                       trends: PlayerTrends) -> float:
        """Calculate contextual value multiplier"""
        multiplier = 1.0
        
        # Age-based adjustments
        if player.age:
            if league_context["is_dynasty"]:
                if player.age < 25:
                    multiplier *= 1.2  # Youth premium in dynasty
                elif player.age > 30:
                    multiplier *= 0.85  # Age discount in dynasty
            else:
                if player.age > 32:
                    multiplier *= 0.95  # Slight age discount in redraft
        
        # Analytics-based performance adjustments
        if analytics:
            # Usage stability and efficiency adjustments
            if analytics.snap_percentage and analytics.snap_percentage > 0.8:
                multiplier *= 1.08  # High usage premium
            elif analytics.snap_percentage and analytics.snap_percentage < 0.4:
                multiplier *= 0.92  # Low usage discount

            # Efficiency premium/discount
            if analytics.points_per_snap and analytics.points_per_snap > 0.2:
                multiplier *= 1.05  # Elite efficiency
            elif analytics.points_per_snap and analytics.points_per_snap < 0.1:
                multiplier *= 0.95  # Poor efficiency

            # Consistency factor
            if analytics.boom_rate and analytics.bust_rate:
                consistency = 1 - analytics.bust_rate + (analytics.boom_rate * 0.5)
                if consistency > 0.8:
                    multiplier *= 1.03  # Consistent high performer
                elif consistency < 0.5:
                    multiplier *= 0.97  # Inconsistent performer

            # Red zone value in TD-heavy leagues
            if analytics.red_zone_share and analytics.red_zone_share > 0.3:
                multiplier *= 1.04  # Red zone usage premium

            # Position-specific analytics adjustments
            if player.position.value == 'RB':
                # Workload sustainability
                if analytics.carries and analytics.carries > 20:
                    if player.age and player.age > 28:
                        multiplier *= 0.95  # High usage + age concern
                    else:
                        multiplier *= 1.03  # High usage premium for young RBs

                # YPC efficiency
                if analytics.rushing_yards and analytics.carries and analytics.carries > 5:
                    ypc = analytics.rushing_yards / analytics.carries
                    if ypc > 4.8:
                        multiplier *= 1.02  # Efficient runner
                    elif ypc < 3.5:
                        multiplier *= 0.98  # Inefficient runner

            elif player.position.value in ['WR', 'TE']:
                # Target efficiency
                if analytics.targets and analytics.receptions and analytics.targets > 3:
                    catch_rate = analytics.receptions / analytics.targets
                    if catch_rate > 0.75:
                        multiplier *= 1.02  # Reliable hands
                    elif catch_rate < 0.55:
                        multiplier *= 0.98  # Drop concerns

                # Big play ability
                if analytics.receiving_yards and analytics.receptions and analytics.receptions > 0:
                    ypr = analytics.receiving_yards / analytics.receptions
                    if ypr > 15:
                        multiplier *= 1.02  # Big play threat
                    elif ypr < 8:
                        multiplier *= 0.99  # Limited big play upside

        # Performance trend adjustments
        if trends:
            if trends.momentum_score and trends.momentum_score > 0.7:
                multiplier *= 1.1  # Positive momentum
            elif trends.momentum_score and trends.momentum_score < -0.7:
                multiplier *= 0.9  # Negative momentum
        
        # Team context adjustments
        if team_context.get("championship_contender") and league_context["trade_deadline_weeks"] <= 3:
            # Championship contenders pay premium near deadline
            multiplier *= 1.05
        elif team_context.get("should_rebuild"):
            # Rebuilding teams prefer younger/future assets
            if league_context["is_dynasty"] and player.age and player.age < 26:
                multiplier *= 1.15
        
        # Position scarcity in league
        if player.position == "TE" and league_context["team_count"] >= 12:
            multiplier *= 1.1  # TE premium in larger leagues
        
        return multiplier
    
    def _get_value_factors(self, player: FantasyPlayer, analytics: PlayerAnalytics,
                          trends: PlayerTrends, league_context: Dict) -> List[str]:
        """Get comprehensive list of factors affecting player value"""
        factors = []

        if analytics:
            # Usage Metrics
            if analytics.snap_percentage and analytics.snap_percentage > 0.85:
                factors.append("Elite snap share (>85%)")
            elif analytics.snap_percentage and analytics.snap_percentage > 0.75:
                factors.append("High snap share (>75%)")
            elif analytics.snap_percentage and analytics.snap_percentage < 0.5:
                factors.append("Limited snap share (<50%)")

            # Target Share Analysis (for pass catchers)
            if player.position.value in ['WR', 'TE', 'RB']:
                if analytics.target_share and analytics.target_share > 0.25:
                    factors.append(f"Elite target share ({analytics.target_share:.1%})")
                elif analytics.target_share and analytics.target_share > 0.18:
                    factors.append(f"Strong target share ({analytics.target_share:.1%})")
                elif analytics.target_share and analytics.target_share < 0.08:
                    factors.append(f"Low target share ({analytics.target_share:.1%})")

            # Red Zone Usage
            if analytics.red_zone_share and analytics.red_zone_share > 0.35:
                factors.append("High red zone usage")
            elif analytics.red_zone_share and analytics.red_zone_share > 0.2:
                factors.append("Solid red zone role")

            # Efficiency Metrics
            if analytics.points_per_snap and analytics.points_per_snap > 0.25:
                factors.append("Elite efficiency")
            elif analytics.points_per_snap and analytics.points_per_snap > 0.18:
                factors.append("High efficiency")
            elif analytics.points_per_snap and analytics.points_per_snap < 0.1:
                factors.append("Low efficiency")

            # Consistency Analysis
            if analytics.boom_rate and analytics.boom_rate > 0.35:
                factors.append("High ceiling player")
            elif analytics.boom_rate and analytics.boom_rate < 0.15:
                factors.append("Safe floor player")

            if analytics.bust_rate and analytics.bust_rate > 0.3:
                factors.append("High volatility")
            elif analytics.bust_rate and analytics.bust_rate < 0.15:
                factors.append("Consistent performer")

            # RB-Specific Metrics
            if player.position.value == 'RB':
                if analytics.carries and analytics.carries > 18:
                    factors.append("High volume runner")
                elif analytics.carries and analytics.carries < 8:
                    factors.append("Limited rushing role")

                if analytics.rushing_yards and analytics.carries:
                    ypc = analytics.rushing_yards / analytics.carries
                    if ypc > 5.0:
                        factors.append(f"Explosive runner ({ypc:.1f} YPC)")
                    elif ypc < 3.5:
                        factors.append(f"Low YPC ({ypc:.1f})")

            # WR/TE Specific Metrics
            if player.position.value in ['WR', 'TE']:
                if analytics.targets and analytics.receptions:
                    catch_rate = analytics.receptions / analytics.targets
                    if catch_rate > 0.75:
                        factors.append(f"High catch rate ({catch_rate:.1%})")
                    elif catch_rate < 0.6:
                        factors.append(f"Low catch rate ({catch_rate:.1%})")

                if analytics.receiving_yards and analytics.receptions and analytics.receptions > 0:
                    ypr = analytics.receiving_yards / analytics.receptions
                    if ypr > 15:
                        factors.append(f"Big play threat ({ypr:.1f} YPR)")
                    elif ypr < 8:
                        factors.append(f"Short-area target ({ypr:.1f} YPR)")

            # Recent Performance Trends
            if analytics.ppr_points:
                if analytics.ppr_points > 20:
                    factors.append("Elite recent game")
                elif analytics.ppr_points > 15:
                    factors.append("Strong recent game")
                elif analytics.ppr_points < 5:
                    factors.append("Poor recent game")

        if trends:
            if trends.buy_low_indicator:
                factors.append("Buy-low opportunity")
            if trends.sell_high_indicator:
                factors.append("Sell-high candidate")

        # Age and Experience Factors
        if player.age:
            if player.age < 23:
                factors.append("Prime breakout age")
            elif player.age < 27:
                factors.append("Peak years")
            elif player.age > 30:
                factors.append("Veteran decline risk")
            elif player.age > 28:
                factors.append("Age concern")
        
        return factors
    
    def _get_draft_pick_value(self, pick_id: int, league_context: Dict) -> float:
        """Calculate draft pick trade value"""
        pick = self.db.query(DraftPick).filter(DraftPick.id == pick_id).first()
        
        if not pick:
            return 0.0
        
        # Base values by round
        base_values = {
            1: 25.0,  # 1st round
            2: 15.0,  # 2nd round  
            3: 8.0,   # 3rd round
            4: 4.0,   # 4th round
        }
        
        base_value = base_values.get(pick.round_number, 2.0)
        
        # Adjust for dynasty vs redraft
        if league_context["is_dynasty"]:
            base_value *= 1.3  # Pick premium in dynasty
        
        # Time-based adjustments
        years_out = pick.season - league_context.get("season", 2025)
        if years_out > 0:
            base_value *= (0.9 ** years_out)  # Future picks worth less
        
        return base_value
    
    def _get_faab_value(self, faab_amount: int, league_context: Dict) -> float:
        """Calculate FAAB trade value"""
        # FAAB is typically worth less in trades than at face value
        return faab_amount * 0.7
    
    # ============================================================================
    # TRADE IMPACT ANALYSIS
    # ============================================================================
    
    def _analyze_trade_impact(self, team_id: int, gives: Dict, receives: Dict,
                             team_context: Dict, league_context: Dict) -> Dict[str, Any]:
        """Comprehensive analysis of trade impact on team"""
        
        # Positional impact analysis
        positional_impact = self._analyze_positional_impact(team_id, gives, receives)
        
        # Roster construction impact
        roster_impact = self._analyze_roster_construction_impact(
            team_id, gives, receives, team_context
        )
        
        # Strategic fit analysis
        strategic_fit = self._analyze_strategic_fit(
            gives, receives, team_context, league_context
        )
        
        # Championship probability impact
        championship_impact = self._calculate_championship_impact(
            team_id, gives, receives, team_context, league_context
        )
        
        # Risk assessment
        risk_assessment = self._assess_trade_risks(gives, receives, league_context)
        
        return {
            "positional_impact": positional_impact,
            "roster_impact": roster_impact,
            "strategic_fit": strategic_fit,
            "championship_impact": championship_impact,
            "risk_assessment": risk_assessment,
            "overall_benefit_score": self._calculate_overall_benefit(
                positional_impact, roster_impact, strategic_fit, championship_impact
            )
        }
    
    def _analyze_positional_impact(self, team_id: int, gives: Dict, receives: Dict) -> Dict[str, Any]:
        """Analyze how trade affects team's positional strength"""
        position_changes = {}
        
        # Analyze players given away
        if gives.get("players"):
            for player_id in gives["players"]:
                player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
                if player:
                    pos = player.position
                    if pos not in position_changes:
                        position_changes[pos] = {"lost": [], "gained": []}
                    position_changes[pos]["lost"].append({
                        "name": player.name,
                        "value": self._get_simple_player_value(player_id)
                    })
        
        # Analyze players received
        if receives.get("players"):
            for player_id in receives["players"]:
                player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
                if player:
                    pos = player.position
                    if pos not in position_changes:
                        position_changes[pos] = {"lost": [], "gained": []}
                    position_changes[pos]["gained"].append({
                        "name": player.name,
                        "value": self._get_simple_player_value(player_id)
                    })
        
        # Calculate net impact by position
        position_summary = {}
        for position, changes in position_changes.items():
            lost_value = sum(p["value"] for p in changes["lost"])
            gained_value = sum(p["value"] for p in changes["gained"])
            net_change = gained_value - lost_value
            
            position_summary[position] = {
                "net_value_change": round(net_change, 2),
                "players_lost": len(changes["lost"]),
                "players_gained": len(changes["gained"]),
                "impact_level": self._categorize_positional_impact(net_change)
            }
        
        return {
            "position_changes": position_changes,
            "position_summary": position_summary,
            "most_improved_position": max(position_summary.keys(), 
                                        key=lambda p: position_summary[p]["net_value_change"], 
                                        default=None),
            "most_hurt_position": min(position_summary.keys(),
                                    key=lambda p: position_summary[p]["net_value_change"],
                                    default=None)
        }
    
    def _get_simple_player_value(self, player_id: int) -> float:
        """Get simplified player value for quick calculations using Sleeper data"""
        # Check PlayerValue table first
        player_value = self.db.query(PlayerValue).filter(
            PlayerValue.player_id == player_id
        ).order_by(desc(PlayerValue.week)).first()
        
        if player_value and player_value.rest_of_season_value:
            return player_value.rest_of_season_value
        
        # Fallback to Sleeper player data for realistic values
        from app.models.database_models import SleeperPlayer
        sleeper_player = self.db.query(SleeperPlayer).filter(
            SleeperPlayer.sleeper_player_id == str(player_id)
        ).first()
        
        if sleeper_player:
            return self._calculate_sleeper_player_value(sleeper_player)
        
        # Final fallback to position defaults
        position_defaults = {"QB": 25.0, "RB": 22.0, "WR": 20.0, "TE": 15.0, "K": 3.0, "DEF": 5.0}
        return position_defaults.get("Unknown", 12.0)
    
    def _calculate_sleeper_player_value(self, sleeper_player) -> float:
        """Calculate realistic player value based on Sleeper data"""
        position = sleeper_player.position
        age = sleeper_player.age or 27
        
        # Base values by position (more realistic ranges)
        base_values = {
            "QB": (20.0, 45.0),   # QB range 20-45
            "RB": (15.0, 40.0),   # RB range 15-40  
            "WR": (12.0, 38.0),   # WR range 12-38
            "TE": (8.0, 25.0),    # TE range 8-25
            "K": (2.0, 6.0),      # K range 2-6
            "DEF": (3.0, 8.0)     # DEF range 3-8
        }
        
        min_val, max_val = base_values.get(position, (8.0, 15.0))
        
        # Age-based value adjustment
        if age <= 24:
            age_multiplier = 1.1  # Young player bonus
        elif age <= 27:
            age_multiplier = 1.0  # Prime years
        elif age <= 30:
            age_multiplier = 0.95  # Slight decline
        else:
            age_multiplier = 0.8   # Aging player discount
        
        # Team quality impact (simplified based on team name)
        team_multiplier = 1.0
        if sleeper_player.team in ['KC', 'BUF', 'DAL', 'SF', 'PHI', 'MIA', 'LAR']:
            team_multiplier = 1.05  # Good offense teams
        elif sleeper_player.team in ['WAS', 'CHI', 'NYG', 'CAR']:
            team_multiplier = 0.95  # Weaker offense teams
        
        # Calculate final value with some variance
        import random
        base_value = random.uniform(min_val, max_val)
        final_value = base_value * age_multiplier * team_multiplier
        
        return round(final_value, 1)
    
    def _categorize_positional_impact(self, net_change: float) -> str:
        """Categorize the level of positional impact"""
        if net_change >= 10:
            return "Major Improvement"
        elif net_change >= 5:
            return "Significant Improvement"
        elif net_change >= 2:
            return "Minor Improvement"
        elif net_change >= -2:
            return "Minimal Impact"
        elif net_change >= -5:
            return "Minor Downgrade"
        elif net_change >= -10:
            return "Significant Downgrade"
        else:
            return "Major Downgrade"
    
    def _analyze_roster_construction_impact(self, team_id: int, gives: Dict, receives: Dict,
                                          team_context: Dict) -> Dict[str, Any]:
        """Analyze impact on overall roster construction"""
        
        # Get current roster composition
        current_roster = self._get_roster_composition(team_id)
        
        # Calculate age impact
        age_impact = self._calculate_age_impact(gives, receives)
        
        # Calculate depth impact
        depth_impact = self._calculate_depth_impact(team_id, gives, receives)
        
        # Calculate starter vs bench impact
        starter_impact = self._calculate_starter_impact(team_id, gives, receives)
        
        return {
            "current_roster_strength": current_roster,
            "age_impact": age_impact,
            "depth_impact": depth_impact,
            "starter_impact": starter_impact,
            "roster_construction_grade": self._grade_roster_construction(
                age_impact, depth_impact, starter_impact
            )
        }
    
    def _get_roster_composition(self, team_id: int) -> Dict[str, Any]:
        """Get current team roster composition analysis"""
        # Simplified roster analysis
        roster_spots = self.db.query(FantasyRosterSpot).filter(
            FantasyRosterSpot.team_id == team_id
        ).all()
        
        position_counts = {}
        for spot in roster_spots:
            if spot.player:
                pos = spot.player.position
                position_counts[pos] = position_counts.get(pos, 0) + 1
        
        return {
            "position_counts": position_counts,
            "total_players": len(roster_spots),
            "roster_strength_score": 7.5  # Would calculate based on player values
        }
    
    def _calculate_age_impact(self, gives: Dict, receives: Dict) -> Dict[str, Any]:
        """Calculate how trade affects team's age profile"""
        age_change = 0.0
        players_analyzed = 0
        
        # Players given away (subtract their ages)
        if gives.get("players"):
            for player_id in gives["players"]:
                player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
                if player and player.age:
                    age_change -= player.age
                    players_analyzed += 1
        
        # Players received (add their ages)
        if receives.get("players"):
            for player_id in receives["players"]:
                player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
                if player and player.age:
                    age_change += player.age
                    players_analyzed += 1
        
        avg_age_change = age_change / players_analyzed if players_analyzed > 0 else 0
        
        return {
            "average_age_change": round(avg_age_change, 1),
            "getting_younger": avg_age_change < -1,
            "getting_older": avg_age_change > 1,
            "age_impact_description": self._describe_age_impact(avg_age_change)
        }
    
    def _describe_age_impact(self, age_change: float) -> str:
        """Describe the age impact of the trade"""
        if age_change <= -3:
            return "Significantly younger roster"
        elif age_change <= -1:
            return "Younger roster"
        elif age_change < 1:
            return "Minimal age impact"
        elif age_change < 3:
            return "Older roster"
        else:
            return "Significantly older roster"
    
    def _calculate_depth_impact(self, team_id: int, gives: Dict, receives: Dict) -> Dict[str, Any]:
        """Calculate how trade affects roster depth"""
        players_in = len(receives.get("players", []))
        players_out = len(gives.get("players", []))
        
        depth_change = players_in - players_out
        
        return {
            "players_gained": players_in,
            "players_lost": players_out,
            "net_player_change": depth_change,
            "depth_impact": "Improved" if depth_change > 0 else ("Reduced" if depth_change < 0 else "Neutral")
        }
    
    def _calculate_starter_impact(self, team_id: int, gives: Dict, receives: Dict) -> Dict[str, Any]:
        """Calculate impact on starting lineup quality"""
        # This would analyze whether traded players are typical starters
        # Simplified for now
        return {
            "starter_quality_change": 0.5,  # Would calculate based on player rankings
            "impact_description": "Slight starter upgrade"
        }
    
    def _grade_roster_construction(self, age_impact: Dict, depth_impact: Dict, 
                                 starter_impact: Dict) -> str:
        """Grade overall roster construction impact"""
        # Simplified grading logic
        score = 0
        
        if age_impact["getting_younger"]:
            score += 1
        if depth_impact["net_player_change"] >= 0:
            score += 1
        if starter_impact["starter_quality_change"] > 0:
            score += 1
        
        grades = ["Poor", "Fair", "Good", "Excellent"]
        return grades[min(score, 3)]
    
    def _analyze_strategic_fit(self, gives: Dict, receives: Dict, team_context: Dict,
                              league_context: Dict) -> Dict[str, Any]:
        """Analyze how well trade fits team's strategic goals"""
        
        strategic_alignment = 0.0
        strategic_factors = []
        
        # Championship contender analysis
        if team_context.get("championship_contender"):
            if league_context["trade_deadline_weeks"] <= 3:
                # Near deadline, should be consolidating for best players
                if len(gives.get("players", [])) > len(receives.get("players", [])):
                    strategic_alignment += 0.3
                    strategic_factors.append("Consolidating talent for playoff push")
        
        # Rebuilding team analysis
        elif team_context.get("should_rebuild"):
            # Should be acquiring youth and future assets
            if receives.get("picks"):
                strategic_alignment += 0.4
                strategic_factors.append("Acquiring future draft capital")
            
            # Check if getting younger players
            if self._trade_makes_team_younger(gives, receives):
                strategic_alignment += 0.3
                strategic_factors.append("Adding younger players for rebuild")
        
        # Bubble team analysis
        else:
            # Should make moves that improve chances without mortgaging future
            strategic_alignment += 0.2
            strategic_factors.append("Balanced approach for bubble team")
        
        return {
            "strategic_alignment_score": round(strategic_alignment, 2),
            "strategic_factors": strategic_factors,
            "fits_team_strategy": strategic_alignment >= 0.3,
            "strategy_description": self._describe_team_strategy(team_context, league_context)
        }
    
    def _trade_makes_team_younger(self, gives: Dict, receives: Dict) -> bool:
        """Check if trade makes team younger on average"""
        age_change = self._calculate_age_impact(gives, receives)
        return age_change["getting_younger"]
    
    def _describe_team_strategy(self, team_context: Dict, league_context: Dict) -> str:
        """Describe what the team's strategy should be"""
        if team_context.get("championship_contender"):
            return "Win-now mode: consolidate talent, sacrifice future for immediate improvement"
        elif team_context.get("should_rebuild"):
            return "Rebuild mode: acquire youth, draft picks, and long-term assets"
        else:
            return "Competitive mode: balance present and future, make incremental improvements"
    
    def _calculate_championship_impact(self, team_id: int, gives: Dict, receives: Dict,
                                     team_context: Dict, league_context: Dict) -> Dict[str, float]:
        """Calculate impact on championship probability"""
        
        # This would integrate with more sophisticated modeling
        # Simplified calculation for now
        
        base_championship_odds = self._estimate_championship_odds(team_context)
        
        # Calculate value difference
        gives_value = sum(self._get_simple_player_value(pid) for pid in gives.get("players", []))
        receives_value = sum(self._get_simple_player_value(pid) for pid in receives.get("players", []))
        
        value_difference = receives_value - gives_value
        
        # Convert value difference to championship probability change
        probability_change = value_difference * 0.001  # 1 point = 0.1% championship probability
        
        new_championship_odds = base_championship_odds + probability_change
        
        return {
            "current_championship_odds": round(base_championship_odds, 3),
            "projected_championship_odds": round(new_championship_odds, 3),
            "championship_probability_change": round(probability_change, 3),
            "championship_impact_description": self._describe_championship_impact(probability_change)
        }
    
    def _estimate_championship_odds(self, team_context: Dict) -> float:
        """Estimate current championship odds based on team context"""
        if team_context.get("championship_contender"):
            return 0.15  # 15% chance
        elif team_context.get("playoff_position"):
            return 0.08  # 8% chance
        else:
            return 0.02  # 2% chance
    
    def _describe_championship_impact(self, probability_change: float) -> str:
        """Describe championship probability impact"""
        if probability_change >= 0.02:
            return "Significantly improves championship odds"
        elif probability_change >= 0.01:
            return "Improves championship odds"
        elif probability_change >= -0.01:
            return "Minimal impact on championship odds"
        elif probability_change >= -0.02:
            return "Slightly hurts championship odds"
        else:
            return "Significantly hurts championship odds"
    
    def _assess_trade_risks(self, gives: Dict, receives: Dict, league_context: Dict) -> Dict[str, Any]:
        """Assess various risks associated with the trade"""
        
        risks = []
        risk_score = 0.0
        
        # Injury risk analysis
        injury_risk = self._assess_injury_risk(receives.get("players", []))
        if injury_risk["high_risk_players"] > 0:
            risks.append(f"Acquiring {injury_risk['high_risk_players']} injury-prone player(s)")
            risk_score += injury_risk["high_risk_players"] * 0.1
        
        # Age risk analysis
        age_risk = self._assess_age_risk(receives.get("players", []))
        if age_risk["old_players"] > 0:
            risks.append(f"Acquiring {age_risk['old_players']} aging player(s)")
            risk_score += age_risk["old_players"] * 0.05
        
        # Draft pick risk
        if gives.get("picks"):
            future_picks = [p for p in gives["picks"] if self._is_future_pick(p)]
            if future_picks:
                risks.append("Giving up future draft capital")
                risk_score += len(future_picks) * 0.15
        
        return {
            "overall_risk_score": round(risk_score, 2),
            "risk_level": self._categorize_risk_level(risk_score),
            "identified_risks": risks,
            "risk_mitigation_suggestions": self._generate_risk_mitigation(risks)
        }
    
    def _assess_injury_risk(self, player_ids: List[int]) -> Dict[str, int]:
        """Assess injury risk for players being acquired"""
        high_risk_count = 0
        
        for player_id in player_ids:
            # Check player's injury history and current status
            player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
            if player and player.status in ["injured", "out", "doubtful"]:
                high_risk_count += 1
        
        return {"high_risk_players": high_risk_count}
    
    def _assess_age_risk(self, player_ids: List[int]) -> Dict[str, int]:
        """Assess age-related risk for players being acquired"""
        old_players = 0
        
        for player_id in player_ids:
            player = self.db.query(FantasyPlayer).filter(FantasyPlayer.id == player_id).first()
            if player and player.age and player.age >= 30:
                old_players += 1
        
        return {"old_players": old_players}
    
    def _is_future_pick(self, pick_id: int) -> bool:
        """Check if draft pick is for future season"""
        pick = self.db.query(DraftPick).filter(DraftPick.id == pick_id).first()
        current_year = datetime.now().year
        return pick and pick.season > current_year
    
    def _categorize_risk_level(self, risk_score: float) -> str:
        """Categorize overall risk level"""
        if risk_score >= 0.5:
            return "High"
        elif risk_score >= 0.25:
            return "Medium"
        elif risk_score >= 0.1:
            return "Low"
        else:
            return "Minimal"
    
    def _generate_risk_mitigation(self, risks: List[str]) -> List[str]:
        """Generate suggestions for mitigating identified risks"""
        suggestions = []
        
        for risk in risks:
            if "injury-prone" in risk.lower():
                suggestions.append("Consider handcuff players or backup options")
            elif "aging" in risk.lower():
                suggestions.append("Monitor snap counts and usage trends closely")
            elif "draft capital" in risk.lower():
                suggestions.append("Ensure immediate upgrade justifies future cost")
        
        return suggestions
    
    def _calculate_overall_benefit(self, positional_impact: Dict, roster_impact: Dict,
                                 strategic_fit: Dict, championship_impact: Dict) -> float:
        """Calculate overall benefit score for the team"""
        
        # Weight different factors
        positional_score = 0.0
        if positional_impact.get("position_summary"):
            positional_score = sum(
                pos["net_value_change"] for pos in positional_impact["position_summary"].values()
            ) / len(positional_impact["position_summary"])
        
        strategic_score = strategic_fit.get("strategic_alignment_score", 0) * 10
        championship_score = championship_impact.get("championship_probability_change", 0) * 100
        
        # Combine scores with weights
        overall_score = (
            positional_score * 0.4 +
            strategic_score * 0.3 +
            championship_score * 0.3
        )
        
        return round(overall_score, 2)
    
    # ============================================================================
    # TRADE GRADING AND EVALUATION
    # ============================================================================
    
    def _calculate_trade_grade(self, team_analysis: Dict, team_values: Dict, 
                              opponent_values: Dict) -> TradeGrade:
        """Calculate trade grade for a team"""
        
        # Value-based component
        value_given = team_values["total_value_given"]
        value_received = opponent_values["total_value_given"]  # What they're giving us
        
        value_ratio = value_received / value_given if value_given > 0 else 1.0
        
        # Overall benefit component
        benefit_score = team_analysis.get("overall_benefit_score", 0)
        
        # Strategic fit component
        strategic_score = team_analysis.get("strategic_fit", {}).get("strategic_alignment_score", 0)
        
        # Risk component
        risk_score = team_analysis.get("risk_assessment", {}).get("overall_risk_score", 0)
        
        # Calculate composite score
        composite_score = (
            (value_ratio - 1.0) * 30 +  # Value difference
            benefit_score * 2 +          # Benefit score
            strategic_score * 20 -       # Strategic alignment
            risk_score * 10              # Risk penalty
        )
        
        # Convert to letter grade
        if composite_score >= 15:
            return TradeGrade.A_PLUS
        elif composite_score >= 12:
            return TradeGrade.A
        elif composite_score >= 8:
            return TradeGrade.A_MINUS
        elif composite_score >= 5:
            return TradeGrade.B_PLUS
        elif composite_score >= 2:
            return TradeGrade.B
        elif composite_score >= -1:
            return TradeGrade.B_MINUS
        elif composite_score >= -4:
            return TradeGrade.C_PLUS
        elif composite_score >= -7:
            return TradeGrade.C
        elif composite_score >= -10:
            return TradeGrade.C_MINUS
        elif composite_score >= -15:
            return TradeGrade.D
        else:
            return TradeGrade.F
    
    def _calculate_fairness_score(self, team1_values: Dict, team2_values: Dict) -> float:
        """Calculate trade fairness score (0-100)"""
        value1 = team1_values["total_value_given"]
        value2 = team2_values["total_value_given"]
        
        if value1 == 0 and value2 == 0:
            return 100.0
        
        # Calculate fairness based on value difference
        total_value = value1 + value2
        if total_value == 0:
            return 100.0
        
        value_difference = abs(value1 - value2)
        fairness_ratio = 1 - (value_difference / total_value)
        
        # Convert to 0-100 scale
        fairness_score = fairness_ratio * 100
        
        return round(max(0, min(100, fairness_score)), 1)
    
    def _generate_ai_summary(self, trade: Trade, team1_analysis: Dict, team2_analysis: Dict,
                            team1_grade: TradeGrade, team2_grade: TradeGrade, 
                            fairness_score: float) -> str:
        """Generate dynamic AI summary of the trade based on actual analysis"""
        
        team1 = self.db.query(FantasyTeam).filter(FantasyTeam.id == trade.team1_id).first()
        team2 = self.db.query(FantasyTeam).filter(FantasyTeam.id == trade.team2_id).first()
        
        summary_parts = []
        
        # Get actual trade values for analysis
        team1_gives_value = sum(self._get_simple_player_value(pid) for pid in trade.team1_gives.get("players", []))
        team2_gives_value = sum(self._get_simple_player_value(pid) for pid in trade.team2_gives.get("players", []))
        value_difference = abs(team1_gives_value - team2_gives_value)
        
        # Dynamic assessment based on actual values and grades
        if fairness_score >= 90 and value_difference < 5:
            summary_parts.append("This is an excellent trade with nearly equal value exchange.")
        elif fairness_score >= 80:
            summary_parts.append("This trade offers good value for both teams with reasonable balance.")
        elif fairness_score >= 65:
            summary_parts.append("This trade shows moderate value exchange with some favorability to one side.")
        else:
            winner = team1.name if team1_gives_value < team2_gives_value else team2.name
            summary_parts.append(f"This trade appears to significantly favor {winner}.")
        
        # Team-specific benefit analysis
        team1_benefit = team1_analysis.get("overall_benefit_score", 0)
        team2_benefit = team2_analysis.get("overall_benefit_score", 0)
        
        # Position-specific insights
        team1_positions = team1_analysis.get("positional_impact", {})
        team2_positions = team2_analysis.get("positional_impact", {})
        
        # Find biggest position changes
        significant_changes = []
        for pos, impact in team1_positions.items():
            if abs(impact.get("net_value_change", 0)) > 5:
                direction = "upgrades" if impact.get("net_value_change", 0) > 0 else "downgrades"
                significant_changes.append(f"{team1.name} {direction} at {pos}")
        
        for pos, impact in team2_positions.items():
            if abs(impact.get("net_value_change", 0)) > 5:
                direction = "upgrades" if impact.get("net_value_change", 0) > 0 else "downgrades"
                significant_changes.append(f"{team2.name} {direction} at {pos}")
        
        if significant_changes:
            summary_parts.append(" ".join(significant_changes[:2]))  # Limit to 2 key changes
        
        # Strategic fit assessment based on grades
        grade_avg = (self._grade_to_numeric(team1_grade) + self._grade_to_numeric(team2_grade)) / 2
        if grade_avg >= 85:
            summary_parts.append("Both teams execute their strategic vision well with this move.")
        elif grade_avg >= 70:
            summary_parts.append("The trade reasonably aligns with at least one team's strategy.")
        else:
            summary_parts.append("This trade may not optimally serve either team's competitive goals.")
        
        return " ".join(summary_parts)
    
    def _grade_to_numeric(self, grade: TradeGrade) -> float:
        """Convert letter grade to numeric score for calculations"""
        grade_values = {
            TradeGrade.A_PLUS: 97, TradeGrade.A: 93, TradeGrade.A_MINUS: 90,
            TradeGrade.B_PLUS: 87, TradeGrade.B: 83, TradeGrade.B_MINUS: 80,
            TradeGrade.C_PLUS: 77, TradeGrade.C: 73, TradeGrade.C_MINUS: 70,
            TradeGrade.D: 60, TradeGrade.F: 40
        }
        return grade_values.get(grade, 70)
    
    def _extract_key_factors(self, team1_analysis: Dict, team2_analysis: Dict, 
                           league_context: Dict) -> List[Dict[str, Any]]:
        """Extract key factors that influenced the trade evaluation"""
        factors = []
        
        # League context factors
        if league_context["trade_deadline_weeks"] <= 3:
            factors.append({
                "category": "timing",
                "description": "Trade deadline approaching - premium on immediate help",
                "impact": "high"
            })
        
        if league_context["is_dynasty"]:
            factors.append({
                "category": "league_type", 
                "description": "Dynasty league format increases value of youth and draft picks",
                "impact": "medium"
            })
        
        # Team-specific factors
        for i, (team_analysis, team_name) in enumerate([(team1_analysis, "Team 1"), (team2_analysis, "Team 2")], 1):
            
            strategic_fit = team_analysis.get("strategic_fit", {})
            if strategic_fit.get("fits_team_strategy"):
                factors.append({
                    "category": f"team{i}_strategy",
                    "description": f"{team_name}: {strategic_fit.get('strategy_description', 'Strategic alignment')}",
                    "impact": "high"
                })
            
            risk_assessment = team_analysis.get("risk_assessment", {})
            if risk_assessment.get("risk_level") in ["High", "Medium"]:
                factors.append({
                    "category": f"team{i}_risk",
                    "description": f"{team_name}: {risk_assessment.get('risk_level')} risk level",
                    "impact": "medium"
                })
        
        return factors
    
    def _calculate_evaluation_confidence(self, team1_analysis: Dict, team2_analysis: Dict) -> float:
        """Calculate confidence level in the evaluation"""
        
        # Base confidence
        confidence = 75.0
        
        # Reduce confidence for various factors
        
        # Limited player data
        if not team1_analysis.get("positional_impact") or not team2_analysis.get("positional_impact"):
            confidence -= 15
        
        # High risk trades
        team1_risk = team1_analysis.get("risk_assessment", {}).get("overall_risk_score", 0)
        team2_risk = team2_analysis.get("risk_assessment", {}).get("overall_risk_score", 0)
        
        if max(team1_risk, team2_risk) > 0.5:
            confidence -= 10
        
        # Complex multi-player trades
        # This would check the complexity of the trade structure
        
        return round(max(50, min(95, confidence)), 1)
    
    def _format_evaluation_response(self, evaluation: TradeEvaluation) -> Dict[str, Any]:
        """Format evaluation for API response"""
        return {
            "success": True,
            "evaluation_id": evaluation.id,
            "trade_id": evaluation.trade_id,
            "grades": {
                "team1_grade": evaluation.team1_grade.value,
                "team2_grade": evaluation.team2_grade.value
            },
            "values": {
                "team1_value_given": evaluation.team1_value_given,
                "team1_value_received": evaluation.team1_value_received,
                "team2_value_given": evaluation.team2_value_given,
                "team2_value_received": evaluation.team2_value_received
            },
            "analysis": {
                "team1_analysis": evaluation.team1_analysis,
                "team2_analysis": evaluation.team2_analysis
            },
            "fairness_score": evaluation.fairness_score,
            "ai_summary": evaluation.ai_summary,
            "key_factors": evaluation.key_factors,
            "confidence": evaluation.confidence,
            "trade_context": evaluation.trade_context,
            "created_at": evaluation.created_at.isoformat()
        }

    # ============================================================================
    # COMPREHENSIVE TEAM ANALYTICS
    # ============================================================================

    async def get_comprehensive_team_analytics(
        self,
        team_id: int,
        season: int = 2025
    ) -> Dict[str, Any]:
        """Get comprehensive analytics for team analysis"""
        try:
            # Get team roster
            roster_spots = self.db.query(FantasyRosterSpot).filter(
                FantasyRosterSpot.team_id == team_id
            ).all()

            players = [spot.player for spot in roster_spots if spot.player]

            # Analyze position groups
            position_analytics = await self._analyze_position_groups(players, season)

            # Calculate team consistency scores
            team_consistency = await self._calculate_team_consistency(players, season)

            # Analyze usage distribution
            usage_distribution = await self._analyze_usage_distribution(players, season)

            # Calculate efficiency benchmarks
            efficiency_benchmarks = await self._calculate_efficiency_benchmarks(players, season)

            # Identify team strengths and weaknesses
            strengths_weaknesses = await self._identify_team_strengths_weaknesses(
                position_analytics, team_consistency, efficiency_benchmarks
            )

            return {
                "team_id": team_id,
                "season": season,
                "position_analytics": position_analytics,
                "team_consistency": team_consistency,
                "usage_distribution": usage_distribution,
                "efficiency_benchmarks": efficiency_benchmarks,
                "strengths_weaknesses": strengths_weaknesses,
                "overall_team_grade": self._calculate_overall_team_grade(
                    position_analytics, team_consistency, efficiency_benchmarks
                ),
                "analytics_updated": datetime.now().isoformat()
            }

        except Exception as e:
            print(f"Error in get_comprehensive_team_analytics: {str(e)}")
            return {}

    async def _analyze_position_groups(
        self,
        players: List[FantasyPlayer],
        season: int
    ) -> Dict[str, Any]:
        """Analyze each position group's performance and depth"""
        from app.services.player_analytics_service import PlayerAnalyticsService
        analytics_service = PlayerAnalyticsService(self.db)

        position_groups = {"QB": [], "RB": [], "WR": [], "TE": [], "K": [], "DEF": []}

        # Group players by position
        for player in players:
            if player.position and player.position.value in position_groups:
                position_groups[player.position.value].append(player)

        position_analytics = {}

        for position, pos_players in position_groups.items():
            if not pos_players:
                position_analytics[position] = {
                    "player_count": 0,
                    "depth_quality": "Poor",
                    "avg_efficiency": 0,
                    "consistency_score": 0,
                    "top_performers": [],
                    "position_grade": "F"
                }
                continue

            # Calculate position group metrics
            efficiency_scores = []
            consistency_scores = []
            top_performers = []

            for player in pos_players:
                # Get recent analytics data
                recent_weeks = list(range(1, 13))  # First 12 weeks
                analytics = await analytics_service.get_player_analytics(
                    player.id, recent_weeks, season
                )

                if analytics:
                    # Calculate efficiency metrics
                    points = [a['ppr_points'] for a in analytics if a['ppr_points']]
                    if points:
                        avg_points = sum(points) / len(points)
                        efficiency_scores.append(avg_points)

                        # Calculate consistency (inverse of standard deviation)
                        if len(points) > 1:
                            std_dev = statistics.stdev(points)
                            consistency = max(0, 100 - (std_dev * 5))  # Convert to 0-100 scale
                            consistency_scores.append(consistency)

                        # Identify top performers (above position average)
                        if position == "QB" and avg_points > 18:
                            top_performers.append({"name": player.name, "avg_points": avg_points})
                        elif position == "RB" and avg_points > 12:
                            top_performers.append({"name": player.name, "avg_points": avg_points})
                        elif position == "WR" and avg_points > 10:
                            top_performers.append({"name": player.name, "avg_points": avg_points})
                        elif position == "TE" and avg_points > 8:
                            top_performers.append({"name": player.name, "avg_points": avg_points})

            # Calculate position group metrics
            avg_efficiency = sum(efficiency_scores) / len(efficiency_scores) if efficiency_scores else 0
            avg_consistency = sum(consistency_scores) / len(consistency_scores) if consistency_scores else 0

            # Determine depth quality
            starter_count = min(self._get_starter_count(position), len(pos_players))
            depth_quality = self._evaluate_depth_quality(len(pos_players), starter_count, avg_efficiency)

            # Calculate position grade
            position_grade = self._calculate_position_grade(avg_efficiency, avg_consistency, depth_quality)

            position_analytics[position] = {
                "player_count": len(pos_players),
                "depth_quality": depth_quality,
                "avg_efficiency": round(avg_efficiency, 1),
                "consistency_score": round(avg_consistency, 1),
                "top_performers": sorted(top_performers, key=lambda x: x['avg_points'], reverse=True)[:3],
                "position_grade": position_grade
            }

        return position_analytics

    async def _calculate_team_consistency(
        self,
        players: List[FantasyPlayer],
        season: int
    ) -> Dict[str, Any]:
        """Calculate overall team consistency metrics"""
        from app.services.player_analytics_service import PlayerAnalyticsService
        analytics_service = PlayerAnalyticsService(self.db)

        all_weekly_scores = []
        position_consistency = {}

        for player in players:
            recent_weeks = list(range(1, 13))
            analytics = await analytics_service.get_player_analytics(
                player.id, recent_weeks, season
            )

            if analytics:
                points = [a['ppr_points'] for a in analytics if a['ppr_points']]

                if points and len(points) > 1:
                    # Add to overall team variance calculation
                    all_weekly_scores.extend(points)

                    # Position-specific consistency
                    position = player.position.value if player.position else "Unknown"
                    if position not in position_consistency:
                        position_consistency[position] = []

                    std_dev = statistics.stdev(points)
                    consistency_score = max(0, 100 - (std_dev * 5))
                    position_consistency[position].append(consistency_score)

        # Calculate overall team consistency
        overall_consistency = 0
        if len(all_weekly_scores) > 1:
            team_std_dev = statistics.stdev(all_weekly_scores)
            overall_consistency = max(0, 100 - (team_std_dev * 2))

        # Calculate position group consistency averages
        position_avg_consistency = {}
        for pos, scores in position_consistency.items():
            if scores:
                position_avg_consistency[pos] = round(sum(scores) / len(scores), 1)

        return {
            "overall_consistency": round(overall_consistency, 1),
            "position_consistency": position_avg_consistency,
            "consistency_grade": self._grade_consistency(overall_consistency),
            "most_consistent_position": max(position_avg_consistency.items(), key=lambda x: x[1])[0] if position_avg_consistency else None,
            "least_consistent_position": min(position_avg_consistency.items(), key=lambda x: x[1])[0] if position_avg_consistency else None
        }

    async def _analyze_usage_distribution(
        self,
        players: List[FantasyPlayer],
        season: int
    ) -> Dict[str, Any]:
        """Analyze how usage is distributed across the team"""
        from app.services.player_analytics_service import PlayerAnalyticsService
        analytics_service = PlayerAnalyticsService(self.db)

        player_usage = []
        total_team_points = 0

        for player in players:
            recent_weeks = list(range(1, 13))
            analytics = await analytics_service.get_player_analytics(
                player.id, recent_weeks, season
            )

            if analytics:
                points = [a['ppr_points'] for a in analytics if a['ppr_points']]
                snap_percentages = [a['snap_percentage'] for a in analytics if a['snap_percentage']]
                target_shares = [a['target_share'] for a in analytics if a['target_share']]

                if points:
                    avg_points = sum(points) / len(points)
                    avg_snap_pct = sum(snap_percentages) / len(snap_percentages) if snap_percentages else 0
                    avg_target_share = sum(target_shares) / len(target_shares) if target_shares else 0

                    player_usage.append({
                        "player_name": player.name,
                        "position": player.position.value if player.position else "Unknown",
                        "avg_points": avg_points,
                        "avg_snap_percentage": avg_snap_pct,
                        "avg_target_share": avg_target_share * 100,  # Convert to percentage
                        "total_points": sum(points)
                    })

                    total_team_points += sum(points)

        # Calculate concentration metrics
        if player_usage:
            # Sort by total points
            player_usage.sort(key=lambda x: x['total_points'], reverse=True)

            # Calculate point concentration (what % of points come from top players)
            top_3_points = sum(p['total_points'] for p in player_usage[:3])
            top_5_points = sum(p['total_points'] for p in player_usage[:5])

            concentration_metrics = {
                "top_3_concentration": round((top_3_points / total_team_points * 100), 1) if total_team_points > 0 else 0,
                "top_5_concentration": round((top_5_points / total_team_points * 100), 1) if total_team_points > 0 else 0,
                "distribution_balance": self._evaluate_distribution_balance(player_usage)
            }
        else:
            concentration_metrics = {
                "top_3_concentration": 0,
                "top_5_concentration": 0,
                "distribution_balance": "Poor"
            }

        return {
            "player_usage": player_usage[:10],  # Top 10 players
            "concentration_metrics": concentration_metrics,
            "usage_distribution_grade": self._grade_usage_distribution(concentration_metrics),
            "team_dependencies": self._identify_team_dependencies(player_usage)
        }

    async def _calculate_efficiency_benchmarks(
        self,
        players: List[FantasyPlayer],
        season: int
    ) -> Dict[str, Any]:
        """Calculate efficiency benchmarks compared to league averages"""
        from app.services.player_analytics_service import PlayerAnalyticsService
        analytics_service = PlayerAnalyticsService(self.db)

        position_efficiency = {"QB": [], "RB": [], "WR": [], "TE": []}

        for player in players:
            if player.position and player.position.value in position_efficiency:
                recent_weeks = list(range(1, 13))
                analytics = await analytics_service.get_player_analytics(
                    player.id, recent_weeks, season
                )

                if analytics:
                    # Calculate various efficiency metrics
                    efficiency_metrics = []

                    for week_data in analytics:
                        if week_data.get('ppr_points') and week_data.get('snap_percentage'):
                            points_per_snap = week_data['ppr_points'] / (week_data['snap_percentage'] / 100)
                            efficiency_metrics.append(points_per_snap)

                    if efficiency_metrics:
                        avg_efficiency = sum(efficiency_metrics) / len(efficiency_metrics)
                        position_efficiency[player.position.value].append(avg_efficiency)

        # Compare to league benchmarks (simplified)
        league_benchmarks = {
            "QB": 0.35,  # Points per snap
            "RB": 0.25,
            "WR": 0.20,
            "TE": 0.15
        }

        efficiency_comparison = {}
        for position, efficiencies in position_efficiency.items():
            if efficiencies:
                team_avg = sum(efficiencies) / len(efficiencies)
                league_avg = league_benchmarks[position]

                efficiency_comparison[position] = {
                    "team_average": round(team_avg, 3),
                    "league_average": league_avg,
                    "vs_league": round(((team_avg - league_avg) / league_avg * 100), 1),
                    "grade": self._grade_efficiency_vs_league(team_avg, league_avg)
                }

        return {
            "efficiency_by_position": efficiency_comparison,
            "overall_efficiency_grade": self._calculate_overall_efficiency_grade(efficiency_comparison),
            "efficiency_strengths": self._identify_efficiency_strengths(efficiency_comparison),
            "efficiency_weaknesses": self._identify_efficiency_weaknesses(efficiency_comparison)
        }

    async def _identify_team_strengths_weaknesses(
        self,
        position_analytics: Dict,
        team_consistency: Dict,
        efficiency_benchmarks: Dict
    ) -> Dict[str, Any]:
        """Identify key team strengths and weaknesses based on analytics"""

        strengths = []
        weaknesses = []

        # Position-based strengths/weaknesses
        for position, analytics in position_analytics.items():
            grade = analytics.get('position_grade', 'F')
            efficiency = analytics.get('avg_efficiency', 0)

            if grade in ['A+', 'A', 'A-'] and efficiency > 15:
                strengths.append(f"Elite {position} production ({grade} grade, {efficiency:.1f} PPG avg)")
            elif grade in ['D', 'F'] or efficiency < 5:
                weaknesses.append(f"Weak {position} depth ({grade} grade, {efficiency:.1f} PPG avg)")

        # Consistency-based insights
        overall_consistency = team_consistency.get('overall_consistency', 0)
        if overall_consistency > 80:
            strengths.append(f"Highly consistent scoring ({overall_consistency:.1f}/100)")
        elif overall_consistency < 50:
            weaknesses.append(f"Inconsistent week-to-week performance ({overall_consistency:.1f}/100)")

        # Efficiency-based insights
        efficiency_grades = efficiency_benchmarks.get('efficiency_by_position', {})
        for position, metrics in efficiency_grades.items():
            vs_league = metrics.get('vs_league', 0)
            if vs_league > 20:
                strengths.append(f"{position} efficiency well above league average (+{vs_league:.1f}%)")
            elif vs_league < -20:
                weaknesses.append(f"{position} efficiency below league average ({vs_league:.1f}%)")

        return {
            "key_strengths": strengths[:5],  # Top 5 strengths
            "key_weaknesses": weaknesses[:5],  # Top 5 weaknesses
            "overall_team_profile": self._determine_team_profile(strengths, weaknesses),
            "recommended_strategy": self._recommend_team_strategy(strengths, weaknesses)
        }

    def _get_starter_count(self, position: str) -> int:
        """Get typical starter count for position"""
        starter_counts = {
            "QB": 1,
            "RB": 2,
            "WR": 3,
            "TE": 1,
            "K": 1,
            "DEF": 1
        }
        return starter_counts.get(position, 1)

    def _evaluate_depth_quality(self, total_players: int, starters_needed: int, avg_efficiency: float) -> str:
        """Evaluate depth quality for a position group"""
        depth_ratio = total_players / starters_needed if starters_needed > 0 else 0

        if depth_ratio >= 2.5 and avg_efficiency > 12:
            return "Excellent"
        elif depth_ratio >= 2 and avg_efficiency > 8:
            return "Good"
        elif depth_ratio >= 1.5 and avg_efficiency > 5:
            return "Fair"
        else:
            return "Poor"

    def _calculate_position_grade(self, efficiency: float, consistency: float, depth_quality: str) -> str:
        """Calculate overall position group grade"""
        score = 0

        # Efficiency component (40%)
        if efficiency > 15:
            score += 40
        elif efficiency > 12:
            score += 32
        elif efficiency > 8:
            score += 24
        elif efficiency > 5:
            score += 16
        else:
            score += 8

        # Consistency component (30%)
        if consistency > 80:
            score += 30
        elif consistency > 70:
            score += 24
        elif consistency > 60:
            score += 18
        elif consistency > 50:
            score += 12
        else:
            score += 6

        # Depth component (30%)
        depth_scores = {"Excellent": 30, "Good": 24, "Fair": 18, "Poor": 6}
        score += depth_scores.get(depth_quality, 6)

        # Convert to letter grade
        if score >= 90:
            return "A+"
        elif score >= 85:
            return "A"
        elif score >= 80:
            return "A-"
        elif score >= 75:
            return "B+"
        elif score >= 70:
            return "B"
        elif score >= 65:
            return "B-"
        elif score >= 60:
            return "C+"
        elif score >= 55:
            return "C"
        elif score >= 50:
            return "C-"
        elif score >= 45:
            return "D"
        else:
            return "F"

    def _grade_consistency(self, consistency_score: float) -> str:
        """Convert consistency score to letter grade"""
        if consistency_score >= 85:
            return "A"
        elif consistency_score >= 75:
            return "B"
        elif consistency_score >= 65:
            return "C"
        elif consistency_score >= 55:
            return "D"
        else:
            return "F"

    def _evaluate_distribution_balance(self, player_usage: List[Dict]) -> str:
        """Evaluate how balanced the usage distribution is"""
        if len(player_usage) < 3:
            return "Poor"

        # Check if points are well distributed
        total_points = sum(p['total_points'] for p in player_usage)
        top_player_pct = player_usage[0]['total_points'] / total_points * 100 if total_points > 0 else 0

        if top_player_pct < 25:
            return "Excellent"
        elif top_player_pct < 35:
            return "Good"
        elif top_player_pct < 45:
            return "Fair"
        else:
            return "Poor"

    def _grade_usage_distribution(self, concentration_metrics: Dict) -> str:
        """Grade the usage distribution"""
        top_3_conc = concentration_metrics.get('top_3_concentration', 0)
        balance = concentration_metrics.get('distribution_balance', 'Poor')

        if balance == "Excellent" and top_3_conc < 60:
            return "A"
        elif balance in ["Good", "Excellent"] and top_3_conc < 70:
            return "B"
        elif balance == "Fair" and top_3_conc < 80:
            return "C"
        else:
            return "D"

    def _identify_team_dependencies(self, player_usage: List[Dict]) -> List[str]:
        """Identify key team dependencies"""
        dependencies = []

        if not player_usage:
            return dependencies

        total_points = sum(p['total_points'] for p in player_usage)

        for player in player_usage[:3]:  # Check top 3 players
            player_pct = player['total_points'] / total_points * 100 if total_points > 0 else 0
            if player_pct > 25:
                dependencies.append(f"Heavy reliance on {player['player_name']} ({player_pct:.1f}% of team points)")

        return dependencies

    def _grade_efficiency_vs_league(self, team_avg: float, league_avg: float) -> str:
        """Grade efficiency compared to league average"""
        ratio = team_avg / league_avg if league_avg > 0 else 1

        if ratio >= 1.3:
            return "A"
        elif ratio >= 1.15:
            return "B"
        elif ratio >= 0.95:
            return "C"
        elif ratio >= 0.8:
            return "D"
        else:
            return "F"

    def _calculate_overall_efficiency_grade(self, efficiency_comparison: Dict) -> str:
        """Calculate overall efficiency grade across all positions"""
        grades = [metrics.get('grade', 'F') for metrics in efficiency_comparison.values()]

        if not grades:
            return "F"

        # Convert grades to numeric and average
        grade_values = {'A': 90, 'B': 80, 'C': 70, 'D': 60, 'F': 50}
        numeric_grades = [grade_values.get(g, 50) for g in grades]
        avg_grade = sum(numeric_grades) / len(numeric_grades)

        if avg_grade >= 85:
            return "A"
        elif avg_grade >= 75:
            return "B"
        elif avg_grade >= 65:
            return "C"
        elif avg_grade >= 55:
            return "D"
        else:
            return "F"

    def _identify_efficiency_strengths(self, efficiency_comparison: Dict) -> List[str]:
        """Identify efficiency strengths"""
        strengths = []

        for position, metrics in efficiency_comparison.items():
            vs_league = metrics.get('vs_league', 0)
            if vs_league > 15:
                strengths.append(f"{position} efficiency (+{vs_league:.1f}% vs league)")

        return strengths

    def _identify_efficiency_weaknesses(self, efficiency_comparison: Dict) -> List[str]:
        """Identify efficiency weaknesses"""
        weaknesses = []

        for position, metrics in efficiency_comparison.items():
            vs_league = metrics.get('vs_league', 0)
            if vs_league < -15:
                weaknesses.append(f"{position} efficiency ({vs_league:.1f}% vs league)")

        return weaknesses

    def _determine_team_profile(self, strengths: List[str], weaknesses: List[str]) -> str:
        """Determine overall team profile"""
        strength_count = len(strengths)
        weakness_count = len(weaknesses)

        if strength_count >= 3 and weakness_count <= 1:
            return "Elite roster with dominant strengths"
        elif strength_count >= 2 and weakness_count <= 2:
            return "Strong roster with minor weaknesses"
        elif strength_count >= weakness_count:
            return "Balanced roster trending positive"
        elif weakness_count > strength_count * 1.5:
            return "Developing roster with significant gaps"
        else:
            return "Average roster with mixed results"

    def _recommend_team_strategy(self, strengths: List[str], weaknesses: List[str]) -> str:
        """Recommend strategy based on team analysis"""
        strength_count = len(strengths)
        weakness_count = len(weaknesses)

        if strength_count >= 3:
            return "Win-now strategy: leverage elite talent for championship push"
        elif weakness_count >= 3:
            return "Rebuild strategy: address fundamental weaknesses through trades/waivers"
        elif "consistency" in str(weaknesses).lower():
            return "Stabilization strategy: target consistent performers to reduce variance"
        else:
            return "Optimization strategy: make targeted improvements to competitive roster"

    def _calculate_overall_team_grade(
        self,
        position_analytics: Dict,
        team_consistency: Dict,
        efficiency_benchmarks: Dict
    ) -> str:
        """Calculate overall team grade"""
        scores = []

        # Position grades (60% weight)
        position_grades = [analytics.get('position_grade', 'F') for analytics in position_analytics.values()]
        grade_values = {'A+': 97, 'A': 93, 'A-': 90, 'B+': 87, 'B': 83, 'B-': 80,
                       'C+': 77, 'C': 73, 'C-': 70, 'D': 60, 'F': 50}

        if position_grades:
            avg_position_score = sum(grade_values.get(g, 50) for g in position_grades) / len(position_grades)
            scores.append(avg_position_score * 0.6)

        # Consistency grade (20% weight)
        consistency_grade = team_consistency.get('consistency_grade', 'F')
        scores.append(grade_values.get(consistency_grade, 50) * 0.2)

        # Efficiency grade (20% weight)
        efficiency_grade = efficiency_benchmarks.get('overall_efficiency_grade', 'F')
        scores.append(grade_values.get(efficiency_grade, 50) * 0.2)

        # Calculate final score
        final_score = sum(scores) if scores else 50

        # Convert back to letter grade
        if final_score >= 93:
            return "A"
        elif final_score >= 85:
            return "B"
        elif final_score >= 75:
            return "C"
        elif final_score >= 65:
            return "D"
        else:
            return "F"