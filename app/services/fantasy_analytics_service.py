"""
Enhanced Fantasy Analytics Service - Leverages historical data for advanced insights
"""

from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc
from datetime import datetime, timedelta
import logging
import numpy as np
from collections import defaultdict

from app.models.fantasy_models import (
    FantasyPlayer,
    PlayerAnalytics,
    PlayerTrends,
    PlayerValue,
    FantasyLeague,
    FantasyTeam,
    TeamNeedsAnalysis,
    PlayerProjection,
    FantasyPosition,
)
from app.models.player_mapping import PlayerIDMapping

logger = logging.getLogger(__name__)


class FantasyAnalyticsService:
    """Advanced analytics service leveraging historical NFL data"""

    def __init__(self, db: Session):
        self.db = db
        # Get the most recent season in our data
        self.current_season = self._get_current_season()

    def _get_current_season(self) -> int:
        """Get the most recent season in our data"""
        latest = self.db.query(func.max(PlayerAnalytics.season)).scalar()
        return latest if latest else datetime.now().year

    def get_player_trend_analysis(
        self, player_id: int, weeks_back: int = 4
    ) -> Dict[str, Any]:
        """Analyze player trends using historical data"""
        try:
            # Get recent analytics data
            recent_games = (
                self.db.query(PlayerAnalytics)
                .filter(PlayerAnalytics.player_id == player_id)
                .order_by(PlayerAnalytics.season.desc(), PlayerAnalytics.week.desc())
                .limit(weeks_back)
                .all()
            )

            if not recent_games:
                return {"error": "No data available for player"}

            # Calculate trend metrics
            points = [g.ppr_points for g in recent_games if g.ppr_points is not None]
            targets = [g.targets for g in recent_games if g.targets is not None]
            snaps = [
                g.snap_percentage for g in recent_games if g.snap_percentage is not None
            ]

            # Trend calculations
            points_trend = self._calculate_trend(points)
            targets_trend = self._calculate_trend(targets)
            snap_trend = self._calculate_trend(snaps)

            # Get player info
            player = (
                self.db.query(FantasyPlayer)
                .filter(FantasyPlayer.id == player_id)
                .first()
            )

            return {
                "player_name": player.name if player else "Unknown",
                "games_analyzed": len(recent_games),
                "trends": {
                    "points": {
                        "current_avg": (
                            round(np.mean(points[:2]), 2) if len(points) >= 2 else 0
                        ),
                        "previous_avg": (
                            round(np.mean(points[2:]), 2) if len(points) > 2 else 0
                        ),
                        "trend": points_trend,
                        "raw_data": points,
                    },
                    "targets": {
                        "current_avg": (
                            round(np.mean(targets[:2]), 2) if len(targets) >= 2 else 0
                        ),
                        "previous_avg": (
                            round(np.mean(targets[2:]), 2) if len(targets) > 2 else 0
                        ),
                        "trend": targets_trend,
                        "raw_data": targets,
                    },
                    "snap_share": {
                        "current_avg": (
                            round(np.mean(snaps[:2]), 2) if len(snaps) >= 2 else 0
                        ),
                        "previous_avg": (
                            round(np.mean(snaps[2:]), 2) if len(snaps) > 2 else 0
                        ),
                        "trend": snap_trend,
                        "raw_data": snaps,
                    },
                },
                "consistency": self._calculate_consistency(points),
                "recent_games": [
                    {
                        "week": g.week,
                        "season": g.season,
                        "opponent": g.opponent,
                        "ppr_points": g.ppr_points,
                        "targets": g.targets,
                        "snap_percentage": g.snap_percentage,
                    }
                    for g in recent_games
                ],
            }

        except Exception as e:
            logger.error(f"Error analyzing player trends: {str(e)}")
            return {"error": str(e)}

    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend direction from values"""
        if len(values) < 2:
            return "insufficient_data"

        recent = np.mean(values[: min(2, len(values))])
        older = np.mean(values[min(2, len(values)) :])

        if older == 0:
            return "stable"

        change_pct = ((recent - older) / older) * 100

        if change_pct > 15:
            return "rising_fast"
        elif change_pct > 5:
            return "rising"
        elif change_pct < -15:
            return "falling_fast"
        elif change_pct < -5:
            return "falling"
        else:
            return "stable"

    def _calculate_consistency(self, values: List[float]) -> Dict[str, Any]:
        """Calculate consistency metrics"""
        if len(values) < 3:
            return {"rating": "insufficient_data", "score": 0}

        std_dev = np.std(values)
        mean = np.mean(values)
        cv = (std_dev / mean * 100) if mean > 0 else 100

        # Consistency rating based on coefficient of variation
        if cv < 25:
            rating = "elite"
        elif cv < 40:
            rating = "good"
        elif cv < 60:
            rating = "average"
        else:
            rating = "volatile"

        return {
            "rating": rating,
            "score": round(100 - min(cv, 100), 1),
            "std_dev": round(std_dev, 2),
            "coefficient_variation": round(cv, 2),
        }

    def get_matchup_analysis(
        self, player_id: int, opponent: str, week: int
    ) -> Dict[str, Any]:
        """Analyze player matchup using historical data"""
        try:
            # Get player's historical performance
            player_history = (
                self.db.query(PlayerAnalytics)
                .filter(PlayerAnalytics.player_id == player_id)
                .order_by(PlayerAnalytics.season.desc(), PlayerAnalytics.week.desc())
                .limit(10)
                .all()
            )

            # Get performance against this specific opponent
            vs_opponent = (
                self.db.query(PlayerAnalytics)
                .filter(
                    and_(
                        PlayerAnalytics.player_id == player_id,
                        PlayerAnalytics.opponent == opponent,
                    )
                )
                .all()
            )

            # Get opponent's defensive performance by position
            player = (
                self.db.query(FantasyPlayer)
                .filter(FantasyPlayer.id == player_id)
                .first()
            )
            position = player.position if player else None

            # Calculate matchup metrics
            avg_points = (
                np.mean([g.ppr_points for g in player_history if g.ppr_points])
                if player_history
                else 0
            )

            vs_opp_points = [g.ppr_points for g in vs_opponent if g.ppr_points]
            vs_opp_avg = np.mean(vs_opp_points) if vs_opp_points else avg_points

            # Matchup advantage calculation
            if avg_points > 0:
                matchup_advantage = ((vs_opp_avg - avg_points) / avg_points) * 100
            else:
                matchup_advantage = 0

            # Determine matchup rating
            if matchup_advantage > 20:
                rating = "elite_matchup"
            elif matchup_advantage > 10:
                rating = "favorable"
            elif matchup_advantage < -20:
                rating = "avoid"
            elif matchup_advantage < -10:
                rating = "difficult"
            else:
                rating = "neutral"

            return {
                "player_name": player.name if player else "Unknown",
                "position": position,
                "opponent": opponent,
                "week": week,
                "matchup_rating": rating,
                "matchup_advantage": round(matchup_advantage, 1),
                "season_avg_points": round(avg_points, 2),
                "vs_opponent_avg": round(vs_opp_avg, 2),
                "historical_vs_opponent": {
                    "games_played": len(vs_opponent),
                    "avg_points": round(vs_opp_avg, 2),
                    "best_game": max(vs_opp_points) if vs_opp_points else 0,
                    "worst_game": min(vs_opp_points) if vs_opp_points else 0,
                },
                "recent_form": {
                    "last_3_avg": round(
                        np.mean(
                            [g.ppr_points for g in player_history[:3] if g.ppr_points]
                        ),
                        2,
                    ),
                    "trend": self._calculate_trend(
                        [g.ppr_points for g in player_history if g.ppr_points]
                    ),
                },
            }

        except Exception as e:
            logger.error(f"Error analyzing matchup: {str(e)}")
            return {"error": str(e)}

    def get_breakout_candidates(
        self, position: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Identify potential breakout players based on usage trends"""
        try:
            query = (
                self.db.query(
                    PlayerAnalytics.player_id,
                    func.avg(PlayerAnalytics.snap_percentage).label("avg_snaps"),
                    func.avg(PlayerAnalytics.target_share).label("avg_target_share"),
                    func.avg(PlayerAnalytics.ppr_points).label("avg_points"),
                )
                .filter(
                    # Use data from recent seasons, not just current
                    PlayerAnalytics.season
                    >= (self.current_season - 1)
                )
                .group_by(PlayerAnalytics.player_id)
            )

            # Get players with rising metrics
            candidates = []
            for result in query.all():
                player_id = result[0]

                # Get recent vs older games
                recent = (
                    self.db.query(PlayerAnalytics)
                    .filter(
                        and_(
                            PlayerAnalytics.player_id == player_id,
                            # Use data from recent seasons, not just current
                            PlayerAnalytics.season >= (self.current_season - 1),
                            PlayerAnalytics.week >= 10,
                        )
                    )
                    .all()
                )

                older = (
                    self.db.query(PlayerAnalytics)
                    .filter(
                        and_(
                            PlayerAnalytics.player_id == player_id,
                            # Use data from recent seasons, not just current
                            PlayerAnalytics.season >= (self.current_season - 1),
                            PlayerAnalytics.week < 10,
                        )
                    )
                    .all()
                )

                if len(recent) >= 2 and len(older) >= 3:
                    recent_snaps = np.mean(
                        [g.snap_percentage for g in recent if g.snap_percentage]
                    )
                    older_snaps = np.mean(
                        [g.snap_percentage for g in older if g.snap_percentage]
                    )

                    recent_targets = np.mean(
                        [g.target_share for g in recent if g.target_share]
                    )
                    older_targets = np.mean(
                        [g.target_share for g in older if g.target_share]
                    )

                    # Calculate breakout score
                    snap_increase = recent_snaps - older_snaps
                    target_increase = recent_targets - older_targets

                    if snap_increase > 10 or target_increase > 0.05:
                        player = (
                            self.db.query(FantasyPlayer)
                            .filter(FantasyPlayer.id == player_id)
                            .first()
                        )

                        if player and (not position or player.position == position):
                            breakout_score = (snap_increase * 0.3) + (
                                target_increase * 100 * 0.7
                            )

                            candidates.append(
                                {
                                    "player_id": player_id,
                                    "player_name": player.name,
                                    "position": player.position,
                                    "team": player.team,
                                    "breakout_score": round(breakout_score, 2),
                                    "snap_increase": round(snap_increase, 1),
                                    "target_share_increase": round(
                                        target_increase * 100, 1
                                    ),
                                    "recent_avg_points": round(
                                        np.mean(
                                            [
                                                g.ppr_points
                                                for g in recent
                                                if g.ppr_points
                                            ]
                                        ),
                                        2,
                                    ),
                                    "reasons": self._generate_breakout_reasons(
                                        snap_increase, target_increase
                                    ),
                                }
                            )

            # Sort by breakout score
            candidates.sort(key=lambda x: x["breakout_score"], reverse=True)
            return candidates[:limit]

        except Exception as e:
            logger.error(f"Error finding breakout candidates: {str(e)}")
            return []

    def _generate_breakout_reasons(
        self, snap_increase: float, target_increase: float
    ) -> List[str]:
        """Generate reasons for breakout potential"""
        reasons = []

        if snap_increase > 20:
            reasons.append(f"Major snap increase (+{snap_increase:.1f}%)")
        elif snap_increase > 10:
            reasons.append(f"Rising snap count (+{snap_increase:.1f}%)")

        if target_increase > 0.1:
            reasons.append(
                f"Significant target share increase (+{target_increase*100:.1f}%)"
            )
        elif target_increase > 0.05:
            reasons.append(f"Growing target share (+{target_increase*100:.1f}%)")

        if not reasons:
            reasons.append("Positive usage trends")

        return reasons

    def get_regression_candidates(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Identify players likely to regress based on unsustainable metrics"""
        try:
            # Find players with unsustainable TD rates or efficiency
            query = (
                self.db.query(
                    PlayerAnalytics.player_id,
                    func.avg(PlayerAnalytics.ppr_points).label("avg_points"),
                    func.avg(PlayerAnalytics.points_per_touch).label("avg_efficiency"),
                )
                .filter(
                    # Use data from recent seasons, not just current
                    PlayerAnalytics.season
                    >= (self.current_season - 1)
                )
                .group_by(PlayerAnalytics.player_id)
                .having(
                    func.avg(PlayerAnalytics.ppr_points)
                    > 10  # Focus on relevant players
                )
            )

            candidates = []
            for result in query.all():
                player_id = result[0]
                avg_efficiency = result[2] or 0

                # Get player details
                player = (
                    self.db.query(FantasyPlayer)
                    .filter(FantasyPlayer.id == player_id)
                    .first()
                )
                if not player:
                    continue

                # Position-specific efficiency thresholds
                efficiency_thresholds = {"RB": 1.2, "WR": 1.5, "TE": 1.3, "QB": 0.4}

                threshold = efficiency_thresholds.get(player.position, 1.3)

                if avg_efficiency > threshold * 1.3:  # 30% above normal
                    # Get recent games for TD analysis
                    recent_games = (
                        self.db.query(PlayerAnalytics)
                        .filter(
                            and_(
                                PlayerAnalytics.player_id == player_id,
                                # Use data from recent seasons, not just current
                                PlayerAnalytics.season >= (self.current_season - 1),
                            )
                        )
                        .all()
                    )

                    td_dependent = self._check_td_dependency(recent_games)

                    regression_score = ((avg_efficiency / threshold) - 1) * 50
                    if td_dependent:
                        regression_score += 20

                    candidates.append(
                        {
                            "player_id": player_id,
                            "player_name": player.name,
                            "position": player.position,
                            "team": player.team,
                            "regression_score": round(regression_score, 2),
                            "avg_efficiency": round(avg_efficiency, 2),
                            "expected_efficiency": round(threshold, 2),
                            "td_dependent": td_dependent,
                            "risk_level": self._determine_risk_level(regression_score),
                            "reasons": self._generate_regression_reasons(
                                avg_efficiency, threshold, td_dependent
                            ),
                        }
                    )

            candidates.sort(key=lambda x: x["regression_score"], reverse=True)
            return candidates[:limit]

        except Exception as e:
            logger.error(f"Error finding regression candidates: {str(e)}")
            return []

    def _check_td_dependency(self, games: List[PlayerAnalytics]) -> bool:
        """Check if player is TD dependent"""
        high_td_games = 0
        for game in games:
            if game.ppr_points and game.ppr_points > 15:
                # Rough TD check - if points are high but yardage is low
                yards = (game.receiving_yards or 0) + (game.rushing_yards or 0)
                if yards < 70 and game.ppr_points > 15:
                    high_td_games += 1

        return high_td_games >= len(games) * 0.3

    def _determine_risk_level(self, regression_score: float) -> str:
        """Determine regression risk level"""
        if regression_score > 40:
            return "high"
        elif regression_score > 25:
            return "moderate"
        else:
            return "low"

    def _generate_regression_reasons(
        self, efficiency: float, expected: float, td_dependent: bool
    ) -> List[str]:
        """Generate regression risk reasons"""
        reasons = []

        efficiency_diff = ((efficiency / expected) - 1) * 100
        if efficiency_diff > 50:
            reasons.append(
                f"Unsustainably high efficiency ({efficiency_diff:.0f}% above normal)"
            )
        elif efficiency_diff > 30:
            reasons.append(
                f"Above normal efficiency ({efficiency_diff:.0f}% above expected)"
            )

        if td_dependent:
            reasons.append("TD dependent scoring")

        return reasons

    def get_consistency_rankings(
        self, position: str, scoring_type: str = "ppr"
    ) -> List[Dict[str, Any]]:
        """Rank players by consistency for different scoring formats"""
        try:
            # Determine which points column to use
            points_column = {
                "ppr": PlayerAnalytics.ppr_points,
                "half_ppr": PlayerAnalytics.half_ppr_points,
                "standard": PlayerAnalytics.standard_points,
            }.get(scoring_type, PlayerAnalytics.ppr_points)

            # Get players with enough games
            players = (
                self.db.query(
                    PlayerAnalytics.player_id,
                    func.count(PlayerAnalytics.id).label("games"),
                    func.avg(points_column).label("avg_points"),
                    func.stddev(points_column).label("std_dev"),
                )
                .join(FantasyPlayer)
                .filter(
                    and_(
                        # Use ALL historical data from 2021 onwards
                        PlayerAnalytics.season >= 2021,
                        FantasyPlayer.position == position,
                        points_column.isnot(None),
                    )
                )
                .group_by(PlayerAnalytics.player_id)
                .having(func.count(PlayerAnalytics.id) >= 8)
                .all()
            )

            rankings = []
            for player_id, games, avg_points, std_dev in players:
                if avg_points and avg_points > 5:  # Minimum relevance threshold
                    player = (
                        self.db.query(FantasyPlayer)
                        .filter(FantasyPlayer.id == player_id)
                        .first()
                    )

                    # Calculate consistency score
                    cv = (std_dev / avg_points) * 100 if avg_points > 0 else 100
                    consistency_score = max(0, 100 - cv)

                    # Get boom/bust rates
                    analytics = (
                        self.db.query(PlayerAnalytics)
                        .filter(PlayerAnalytics.player_id == player_id)
                        .order_by(
                            PlayerAnalytics.season.desc(), PlayerAnalytics.week.desc()
                        )
                        .limit(16)
                        .all()
                    )

                    boom_rate = 0
                    bust_rate = 0
                    if analytics:
                        recent_boom = (
                            analytics[0].boom_rate if analytics[0].boom_rate else 0
                        )
                        recent_bust = (
                            analytics[0].bust_rate if analytics[0].bust_rate else 0
                        )
                        boom_rate = recent_boom * 100
                        bust_rate = recent_bust * 100

                    rankings.append(
                        {
                            "player_id": player_id,
                            "player_name": player.name if player else "Unknown",
                            "position": position,
                            "team": player.team if player else "FA",
                            "consistency_score": round(consistency_score, 1),
                            "avg_points": round(avg_points, 2),
                            "std_dev": round(std_dev, 2),
                            "games_analyzed": games,
                            "boom_rate": round(boom_rate, 1),
                            "bust_rate": round(bust_rate, 1),
                            "rating": self._get_consistency_rating(consistency_score),
                        }
                    )

            rankings.sort(key=lambda x: x["consistency_score"], reverse=True)
            return rankings

        except Exception as e:
            logger.error(f"Error calculating consistency rankings: {str(e)}")
            return []

    def _get_consistency_rating(self, score: float) -> str:
        """Get consistency rating label"""
        if score >= 75:
            return "elite"
        elif score >= 60:
            return "reliable"
        elif score >= 45:
            return "average"
        elif score >= 30:
            return "volatile"
        else:
            return "boom_bust"

    def get_advanced_player_projection(
        self, player_id: int, week: int, league_settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate advanced projections using all historical data"""
        try:
            # Get player info
            player = (
                self.db.query(FantasyPlayer)
                .filter(FantasyPlayer.id == player_id)
                .first()
            )
            if not player:
                return {"error": "Player not found"}

            # Get historical performance
            historical = (
                self.db.query(PlayerAnalytics)
                .filter(PlayerAnalytics.player_id == player_id)
                .order_by(PlayerAnalytics.season.desc(), PlayerAnalytics.week.desc())
                .limit(16)
                .all()
            )

            if not historical:
                return {"error": "No historical data available"}

            # Calculate base projection from recent games
            recent_games = historical[:6]
            base_points = np.mean([g.ppr_points for g in recent_games if g.ppr_points])

            # Adjust for scoring format
            scoring_type = league_settings.get("scoring_type", "ppr")
            if scoring_type == "standard":
                points_col = [
                    g.standard_points for g in recent_games if g.standard_points
                ]
            elif scoring_type == "half_ppr":
                points_col = [
                    g.half_ppr_points for g in recent_games if g.half_ppr_points
                ]
            else:
                points_col = [g.ppr_points for g in recent_games if g.ppr_points]

            adjusted_projection = np.mean(points_col) if points_col else base_points

            # Calculate floor and ceiling
            if len(points_col) >= 3:
                floor = np.percentile(points_col, 25)
                ceiling = np.percentile(points_col, 75)
            else:
                floor = adjusted_projection * 0.7
                ceiling = adjusted_projection * 1.4

            # Usage trend adjustment
            trend = self.get_player_trend_analysis(player_id, 4)
            trend_adjustment = 0
            if trend.get("trends"):
                snap_trend = trend["trends"].get("snap_share", {}).get("trend")
                target_trend = trend["trends"].get("targets", {}).get("trend")

                if snap_trend == "rising_fast":
                    trend_adjustment += 2
                elif snap_trend == "rising":
                    trend_adjustment += 1
                elif snap_trend == "falling_fast":
                    trend_adjustment -= 2
                elif snap_trend == "falling":
                    trend_adjustment -= 1

            adjusted_projection += trend_adjustment

            # Generate confidence score
            consistency = self._calculate_consistency(
                [g.ppr_points for g in historical if g.ppr_points]
            )
            confidence = min(95, 50 + consistency["score"] * 0.5)

            return {
                "player_id": player_id,
                "player_name": player.name,
                "position": player.position,
                "week": week,
                "projection": round(adjusted_projection, 2),
                "floor": round(floor, 2),
                "ceiling": round(ceiling, 2),
                "confidence": round(confidence, 1),
                "trend_adjustment": round(trend_adjustment, 1),
                "consistency_rating": consistency["rating"],
                "scoring_type": scoring_type,
                "factors": {
                    "recent_avg": round(base_points, 2),
                    "usage_trend": snap_trend if "snap_trend" in locals() else "stable",
                    "games_analyzed": len(recent_games),
                },
            }

        except Exception as e:
            logger.error(f"Error generating advanced projection: {str(e)}")
            return {"error": str(e)}

    def get_waiver_wire_analytics(
        self, league_id: int, position: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Advanced waiver wire analytics using historical data"""
        try:
            # Get trending players based on recent usage
            trending_query = (
                self.db.query(
                    PlayerAnalytics.player_id,
                    func.avg(PlayerAnalytics.snap_percentage).label("avg_snaps"),
                    func.avg(PlayerAnalytics.target_share).label("avg_targets"),
                )
                .filter(
                    and_(
                        # Use data from recent seasons, not just current
                        PlayerAnalytics.season >= (self.current_season - 1),
                        PlayerAnalytics.week >= 10,
                    )
                )
                .group_by(PlayerAnalytics.player_id)
                .having(func.avg(PlayerAnalytics.snap_percentage) > 40)
            )

            recommendations = []
            for result in trending_query.all():
                player_id = result[0]
                avg_snaps = result[1]

                player = (
                    self.db.query(FantasyPlayer)
                    .filter(FantasyPlayer.id == player_id)
                    .first()
                )
                if not player or (position and player.position != position):
                    continue

                # Check ownership (simplified - would need real ownership data)
                ownership_pct = np.random.uniform(5, 60)  # Placeholder

                if ownership_pct < 50:  # Available in most leagues
                    # Calculate opportunity score
                    opportunity_score = self._calculate_opportunity_score(
                        player_id, avg_snaps
                    )

                    # Get recent performance
                    recent_games = (
                        self.db.query(PlayerAnalytics)
                        .filter(
                            and_(
                                PlayerAnalytics.player_id == player_id,
                                # Use data from recent seasons, not just current
                                PlayerAnalytics.season >= (self.current_season - 1),
                            )
                        )
                        .order_by(PlayerAnalytics.week.desc())
                        .limit(3)
                        .all()
                    )

                    recent_avg = np.mean(
                        [g.ppr_points for g in recent_games if g.ppr_points]
                    )

                    recommendations.append(
                        {
                            "player_id": player_id,
                            "player_name": player.name,
                            "position": player.position,
                            "team": player.team,
                            "ownership_pct": round(ownership_pct, 1),
                            "opportunity_score": round(opportunity_score, 1),
                            "recent_ppg": round(recent_avg, 2),
                            "avg_snap_pct": round(avg_snaps, 1),
                            "priority": self._determine_waiver_priority(
                                opportunity_score, ownership_pct
                            ),
                            "recommendation": self._generate_waiver_recommendation(
                                opportunity_score, player.position
                            ),
                        }
                    )

            recommendations.sort(key=lambda x: x["opportunity_score"], reverse=True)
            return recommendations[:20]

        except Exception as e:
            logger.error(f"Error generating waiver analytics: {str(e)}")
            return []

    def _calculate_opportunity_score(self, player_id: int, avg_snaps: float) -> float:
        """Calculate opportunity score for waiver wire"""
        score = 0

        # Snap percentage contribution
        score += min(avg_snaps / 2, 40)

        # Get recent target share
        recent_targets = (
            self.db.query(func.avg(PlayerAnalytics.target_share))
            .filter(
                and_(
                    PlayerAnalytics.player_id == player_id,
                    # Use data from recent seasons, not just current
                    PlayerAnalytics.season >= (self.current_season - 1),
                    PlayerAnalytics.week >= 10,
                )
            )
            .scalar()
        )

        if recent_targets:
            score += recent_targets * 200  # Weight target share heavily

        # Red zone usage
        rz_usage = (
            self.db.query(func.avg(PlayerAnalytics.red_zone_touches))
            .filter(
                and_(
                    PlayerAnalytics.player_id == player_id,
                    # Use data from recent seasons, not just current
                    PlayerAnalytics.season >= (self.current_season - 1),
                )
            )
            .scalar()
        )

        if rz_usage:
            score += rz_usage * 5

        return min(score, 100)

    def _determine_waiver_priority(
        self, opportunity_score: float, ownership: float
    ) -> str:
        """Determine waiver priority level"""
        if opportunity_score > 70 and ownership < 30:
            return "must_add"
        elif opportunity_score > 50 and ownership < 40:
            return "high_priority"
        elif opportunity_score > 30:
            return "moderate"
        else:
            return "speculative"

    def _generate_waiver_recommendation(
        self, opportunity_score: float, position: str
    ) -> str:
        """Generate waiver wire recommendation text"""
        if opportunity_score > 70:
            return f"Immediate add - Elite opportunity at {position}"
        elif opportunity_score > 50:
            return f"Priority add - Rising {position} with strong usage"
        elif opportunity_score > 30:
            return f"Good stash - Increasing role at {position}"
        else:
            return f"Deep league option - Monitor usage"

    def get_trade_value_analysis(
        self, player_ids: List[int], league_settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze trade value using historical performance and trends"""
        try:
            trade_values = []
            total_value_team1 = 0
            total_value_team2 = 0

            for i, player_id in enumerate(player_ids):
                player = (
                    self.db.query(FantasyPlayer)
                    .filter(FantasyPlayer.id == player_id)
                    .first()
                )
                if not player:
                    continue

                # Calculate player value
                value = self._calculate_player_trade_value(player_id, league_settings)

                trade_values.append(
                    {
                        "player_id": player_id,
                        "player_name": player.name,
                        "position": player.position,
                        "team": player.team,
                        "trade_value": value["value"],
                        "value_tier": value["tier"],
                        "trend": value["trend"],
                        "risk_factors": value["risks"],
                    }
                )

                # Assuming first half is team1, second half is team2
                if i < len(player_ids) / 2:
                    total_value_team1 += value["value"]
                else:
                    total_value_team2 += value["value"]

            # Calculate trade fairness
            if total_value_team1 > 0 and total_value_team2 > 0:
                value_diff = abs(total_value_team1 - total_value_team2)
                avg_value = (total_value_team1 + total_value_team2) / 2
                fairness_pct = 100 - (value_diff / avg_value * 100)
            else:
                fairness_pct = 50

            return {
                "players": trade_values,
                "team1_total_value": round(total_value_team1, 1),
                "team2_total_value": round(total_value_team2, 1),
                "fairness_score": round(fairness_pct, 1),
                "trade_grade": self._get_trade_grade(fairness_pct),
                "recommendation": self._get_trade_recommendation(
                    fairness_pct, total_value_team1, total_value_team2
                ),
            }

        except Exception as e:
            logger.error(f"Error analyzing trade value: {str(e)}")
            return {"error": str(e)}

    def _calculate_player_trade_value(
        self, player_id: int, league_settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate individual player trade value"""
        # Get recent performance
        recent = (
            self.db.query(PlayerAnalytics)
            .filter(PlayerAnalytics.player_id == player_id)
            .order_by(PlayerAnalytics.season.desc(), PlayerAnalytics.week.desc())
            .limit(8)
            .all()
        )

        if not recent:
            return {"value": 0, "tier": "unknown", "trend": "stable", "risks": []}

        # Base value from recent performance
        scoring_type = league_settings.get("scoring_type", "ppr")
        if scoring_type == "ppr":
            points = [g.ppr_points for g in recent if g.ppr_points]
        elif scoring_type == "half_ppr":
            points = [g.half_ppr_points for g in recent if g.half_ppr_points]
        else:
            points = [g.standard_points for g in recent if g.standard_points]

        avg_points = np.mean(points) if points else 0

        # Position-based value scaling
        position = (
            self.db.query(FantasyPlayer.position)
            .filter(FantasyPlayer.id == player_id)
            .scalar()
        )

        position_multipliers = {
            "RB": 1.2,  # RB scarcity
            "WR": 1.0,
            "TE": 0.9,
            "QB": 0.8 if not league_settings.get("superflex") else 1.5,
        }

        multiplier = position_multipliers.get(position, 1.0)
        base_value = avg_points * multiplier

        # Trend adjustment
        trend = self._calculate_trend(points)
        if trend == "rising_fast":
            base_value *= 1.2
        elif trend == "rising":
            base_value *= 1.1
        elif trend == "falling_fast":
            base_value *= 0.8
        elif trend == "falling":
            base_value *= 0.9

        # Determine tier
        if base_value > 20:
            tier = "elite"
        elif base_value > 15:
            tier = "high"
        elif base_value > 10:
            tier = "mid"
        elif base_value > 5:
            tier = "low"
        else:
            tier = "minimal"

        # Risk factors
        risks = []
        consistency = self._calculate_consistency(points)
        if consistency["rating"] == "volatile":
            risks.append("High volatility")

        return {
            "value": round(base_value, 1),
            "tier": tier,
            "trend": trend,
            "risks": risks,
        }

    def _get_trade_grade(self, fairness_score: float) -> str:
        """Get trade grade based on fairness"""
        if fairness_score >= 90:
            return "A+"
        elif fairness_score >= 80:
            return "A"
        elif fairness_score >= 70:
            return "B"
        elif fairness_score >= 60:
            return "C"
        elif fairness_score >= 50:
            return "D"
        else:
            return "F"

    def _get_trade_recommendation(
        self, fairness: float, value1: float, value2: float
    ) -> str:
        """Generate trade recommendation"""
        if fairness >= 80:
            return "Fair trade - Both sides benefit"
        elif fairness >= 60:
            if value1 > value2:
                return "Slight advantage to Team 1"
            else:
                return "Slight advantage to Team 2"
        else:
            if value1 > value2:
                return "Team 1 wins significantly"
            else:
                return "Team 2 wins significantly"
