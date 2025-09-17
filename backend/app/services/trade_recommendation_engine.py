"""
Trade Recommendation Engine - AI-powered trade suggestion system
"""

from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func, not_
from datetime import datetime, timedelta
import logging
import itertools
from collections import defaultdict

from app.models.fantasy_models import (
    FantasyTeam,
    FantasyPlayer,
    FantasyLeague,
    FantasyRosterSpot,
    PlayerValue,
    TeamNeedsAnalysis,
    TradeRecommendation,
    PlayerAnalytics,
    PlayerTrends,
    CompetitorAnalysis,
    DraftPick,
)
from app.models.database_models import SleeperRoster, SleeperPlayer, SleeperLeague
from app.services.trade_analyzer_service import TradeAnalyzerService

logger = logging.getLogger(__name__)


class TradeRecommendationEngine:
    """AI-powered trade recommendation and suggestion system"""

    def __init__(self, db: Session):
        self.db = db
        self.trade_analyzer = TradeAnalyzerService(db)

    # ============================================================================
    # MAIN RECOMMENDATION INTERFACE
    # ============================================================================

    def generate_trade_recommendations(
        self,
        team_id: int,
        league_id: int,
        recommendation_type: str = "all",
        max_recommendations: int = 10,
    ) -> List[Dict[str, Any]]:
        """Generate comprehensive trade recommendations for a team"""
        try:
            logger.info(
                f"Generating recommendations for team_id={team_id}, league_id={league_id}"
            )

            # Validate team and league
            team = (
                self.db.query(FantasyTeam)
                .filter(
                    and_(FantasyTeam.id == team_id, FantasyTeam.league_id == league_id)
                )
                .first()
            )

            if not team:
                logger.info(
                    f"No FantasyTeam found with id={team_id}, league_id={league_id}"
                )
                # Check what teams exist
                all_teams = (
                    self.db.query(FantasyTeam)
                    .filter(FantasyTeam.league_id == league_id)
                    .all()
                )
                logger.info(
                    f"Available teams in league {league_id}: {[(t.id, t.name) for t in all_teams]}"
                )
                return []

            # Get team context and needs
            logger.info("Getting comprehensive team context...")
            team_context = self._get_comprehensive_team_context(team_id, league_id)
            logger.info(
                f"Team context keys: {list(team_context.keys()) if team_context else 'None'}"
            )

            logger.info("Getting league context...")
            league_context = self._get_league_context(league_id)
            logger.info(
                f"League context keys: {list(league_context.keys()) if league_context else 'None'}"
            )

            recommendations = []

            # Generate different types of recommendations
            if recommendation_type in ["all", "position_need"]:
                try:
                    logger.info("Starting position need recommendations...")
                    position_recs = self._generate_position_need_trades(
                        team_context, league_context
                    )
                    logger.info(f"Position need recommendations: {len(position_recs)}")
                    recommendations.extend(position_recs)
                except Exception as e:
                    logger.error(
                        f"Error generating position need recommendations: {str(e)}"
                    )

            if recommendation_type in ["all", "buy_low"]:
                try:
                    logger.info("Starting buy low recommendations...")
                    buy_low_recs = self._generate_buy_low_trades(
                        team_context, league_context
                    )
                    logger.info(f"Buy low recommendations: {len(buy_low_recs)}")
                    recommendations.extend(buy_low_recs)
                except Exception as e:
                    logger.error(f"Error generating buy low recommendations: {str(e)}")

            if recommendation_type in ["all", "sell_high"]:
                try:
                    logger.info("Starting sell high recommendations...")
                    sell_high_recs = self._generate_sell_high_trades(
                        team_context, league_context
                    )
                    logger.info(f"Sell high recommendations: {len(sell_high_recs)}")
                    recommendations.extend(sell_high_recs)
                except Exception as e:
                    logger.error(
                        f"Error generating sell high recommendations: {str(e)}"
                    )

            if recommendation_type in ["all", "consolidation"]:
                try:
                    logger.info("Starting consolidation recommendations...")
                    consolidation_recs = self._generate_consolidation_trades(
                        team_context, league_context
                    )
                    logger.info(
                        f"Consolidation recommendations: {len(consolidation_recs)}"
                    )
                    recommendations.extend(consolidation_recs)
                except Exception as e:
                    logger.error(
                        f"Error generating consolidation recommendations: {str(e)}"
                    )

            if recommendation_type in ["all", "depth"]:
                try:
                    logger.info("Starting depth recommendations...")
                    depth_recs = self._generate_depth_trades(
                        team_context, league_context
                    )
                    logger.info(f"Depth recommendations: {len(depth_recs)}")
                    recommendations.extend(depth_recs)
                except Exception as e:
                    logger.error(f"Error generating depth recommendations: {str(e)}")

            # Score and rank all recommendations
            scored_recommendations = self._score_and_rank_recommendations(
                recommendations, team_context, league_context
            )

            # Filter for mutual benefit and high likelihood
            viable_recommendations = self._filter_viable_recommendations(
                scored_recommendations
            )

            # Store recommendations in database
            self._store_recommendations(
                team_id, league_id, viable_recommendations[:max_recommendations]
            )

            return viable_recommendations[:max_recommendations]

        except Exception as e:
            logger.error(
                f"Failed to generate trade recommendations for team {team_id}: {str(e)}"
            )
            return []

    def find_mutual_benefit_trades(
        self, team_id: int, league_id: int, target_team_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Find trades that benefit both teams involved"""
        try:
            team_context = self._get_comprehensive_team_context(team_id, league_id)
            league_context = self._get_league_context(league_id)

            if target_team_id:
                target_teams = [target_team_id]
            else:
                # Get all other teams in league
                target_teams = (
                    self.db.query(FantasyTeam.id)
                    .filter(
                        and_(
                            FantasyTeam.league_id == league_id,
                            FantasyTeam.id != team_id,
                        )
                    )
                    .all()
                )
                target_teams = [t[0] for t in target_teams]

            mutual_benefit_trades = []

            for other_team_id in target_teams:
                other_team_context = self._get_comprehensive_team_context(
                    other_team_id, league_id
                )

                # Generate potential trades between these two teams
                trade_scenarios = self._generate_bilateral_trade_scenarios(
                    team_context, other_team_context, league_context
                )

                # Evaluate each scenario for mutual benefit
                for scenario in trade_scenarios:
                    mutual_benefit = self._evaluate_mutual_benefit(
                        scenario, team_context, other_team_context, league_context
                    )

                    if mutual_benefit["is_mutually_beneficial"]:
                        scenario["mutual_benefit_analysis"] = mutual_benefit
                        scenario["target_team_id"] = other_team_id
                        mutual_benefit_trades.append(scenario)

            # Sort by mutual benefit score
            mutual_benefit_trades.sort(
                key=lambda x: x["mutual_benefit_analysis"]["benefit_score"],
                reverse=True,
            )

            return mutual_benefit_trades[:15]  # Return top 15 mutual benefit trades

        except Exception as e:
            logger.error(f"Failed to find mutual benefit trades: {str(e)}")
            return []

    # ============================================================================
    # TEAM CONTEXT AND ANALYSIS
    # ============================================================================

    def _get_comprehensive_team_context(
        self, team_id: int, league_id: int
    ) -> Dict[str, Any]:
        """Get comprehensive team context for trade recommendations"""
        team = self.db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()

        # Get roster composition
        roster_spots = (
            self.db.query(FantasyRosterSpot)
            .filter(FantasyRosterSpot.team_id == team_id)
            .all()
        )

        # Group players by position
        roster_by_position = defaultdict(list)
        all_players = []

        # Primary data source: fantasy_roster_spots
        for spot in roster_spots:
            if spot.player:
                player_data = {
                    "id": spot.player.id,
                    "name": spot.player.name,
                    "position": spot.player.position,
                    "team": spot.player.team,
                    "age": spot.player.age,
                }
                roster_by_position[spot.player.position].append(player_data)
                all_players.append(player_data)

        # Fallback: Use Sleeper roster data if fantasy_roster_spots is empty
        if not all_players:
            logger.info(
                f"No fantasy roster data found for team {team_id}, trying Sleeper data"
            )
            sleeper_roster = self._get_sleeper_roster_for_team(team_id)
            if sleeper_roster and sleeper_roster.get("players"):
                logger.info(
                    f"Found Sleeper roster with {len(sleeper_roster['players'])} players"
                )
                for player_data in sleeper_roster["players"]:
                    roster_by_position[player_data["position"]].append(player_data)
                    all_players.append(player_data)

        # Get team needs analysis
        needs_analysis = (
            self.db.query(TeamNeedsAnalysis)
            .filter(TeamNeedsAnalysis.team_id == team_id)
            .order_by(desc(TeamNeedsAnalysis.week))
            .first()
        )

        # Calculate position strengths and needs
        position_strength = self._calculate_position_strengths(
            team_id, roster_by_position
        )
        position_needs = self._identify_position_needs(
            team_id, position_strength, needs_analysis
        )

        # Get tradeable assets
        tradeable_players = self._get_tradeable_players(team_id, roster_by_position)
        tradeable_picks = self._get_tradeable_picks(team_id, league_id)

        # Calculate team's competitive stance
        competitive_analysis = self._analyze_competitive_stance(team, league_id)

        return {
            "team_id": team_id,
            "team_name": team.name,
            "record": {"wins": team.wins, "losses": team.losses},
            "points_for": float(team.points_for) if team.points_for else 0,
            "roster_by_position": dict(roster_by_position),
            "all_players": all_players,
            "position_strength": position_strength,
            "position_needs": position_needs,
            "tradeable_players": tradeable_players,
            "tradeable_picks": tradeable_picks,
            "competitive_analysis": competitive_analysis,
            "needs_analysis": needs_analysis.__dict__ if needs_analysis else {},
            "surplus_positions": self._identify_surplus_positions(position_strength),
            "trade_preferences": self._determine_trade_preferences(
                competitive_analysis
            ),
        }

    def _get_league_context(self, league_id: int) -> Dict[str, Any]:
        """Get league context for recommendations"""
        league = (
            self.db.query(FantasyLeague).filter(FantasyLeague.id == league_id).first()
        )

        current_week = 8  # Would get from NFL schedule service
        trade_deadline_weeks = max(0, 10 - current_week)

        return {
            "league_id": league_id,
            "scoring_type": league.scoring_type or "ppr",
            "team_count": league.team_count or 12,
            "current_week": current_week,
            "trade_deadline_weeks": trade_deadline_weeks,
            "is_dynasty": league.league_type == "dynasty",
            "playoff_teams": league.playoff_teams or 6,
        }

    def _calculate_position_strengths(
        self, team_id: int, roster_by_position: Dict
    ) -> Dict[str, float]:
        """Calculate strength scores for each position"""
        position_strengths = {}

        for position, players in roster_by_position.items():
            if not players:
                position_strengths[position] = 0.0
                continue

            # Get player values for this position
            player_values = []
            for player in players:
                value = self._get_player_positional_value(player["id"], position)
                print(
                    f"DEBUG: Player {player.get('name', 'Unknown')} ({position}) strength value: {value}"
                )
                player_values.append(value)

            # Calculate position strength (weighted average)
            if player_values:
                sorted_values = sorted(player_values, reverse=True)
                # Weight starters more heavily than bench
                if len(sorted_values) >= 2:
                    strength = (
                        sorted_values[0] * 0.6
                        + sorted_values[1] * 0.3
                        + sum(sorted_values[2:]) * 0.1 / max(1, len(sorted_values[2:]))
                    )
                else:
                    strength = sorted_values[0]
            else:
                strength = 0.0

            position_strengths[position] = round(strength, 1)

        return position_strengths

    def _get_player_positional_value(self, player_id: int, position: str) -> float:
        """Get player's positional value score using Sleeper data"""
        # Check PlayerValue table first
        player_value = (
            self.db.query(PlayerValue)
            .filter(PlayerValue.player_id == player_id)
            .order_by(desc(PlayerValue.week))
            .first()
        )

        if player_value and player_value.rest_of_season_value:
            return player_value.rest_of_season_value

        # Use Sleeper player data for realistic values
        sleeper_player = (
            self.db.query(SleeperPlayer)
            .filter(SleeperPlayer.sleeper_player_id == str(player_id))
            .first()
        )

        if sleeper_player:
            return self._calculate_realistic_player_value(sleeper_player)

        # Default values by position if no data
        position_defaults = {
            "QB": 15.0,
            "RB": 18.0,
            "WR": 16.0,
            "TE": 12.0,
            "K": 3.0,
            "DEF": 5.0,
        }
        return position_defaults.get(position, 20.0)

    def _calculate_realistic_player_value(self, sleeper_player) -> float:
        """Calculate realistic player value based on Sleeper data"""
        position = sleeper_player.position
        age = sleeper_player.age or 27

        # Base values by position with realistic ranges
        base_values = {
            "QB": (18.0, 42.0),  # QB range 18-42
            "RB": (14.0, 38.0),  # RB range 14-38
            "WR": (11.0, 36.0),  # WR range 11-36
            "TE": (7.0, 23.0),  # TE range 7-23
            "K": (1.5, 5.5),  # K range 1.5-5.5
            "DEF": (2.5, 7.5),  # DEF range 2.5-7.5
        }

        min_val, max_val = base_values.get(position, (8.0, 15.0))

        # Age-based value with more variance
        if age <= 23:
            age_multiplier = 1.15  # Rookie/sophomore bonus
        elif age <= 26:
            age_multiplier = 1.05  # Prime development years
        elif age <= 29:
            age_multiplier = 1.0  # Peak years
        elif age <= 32:
            age_multiplier = 0.9  # Decline phase
        else:
            age_multiplier = 0.75  # Late career

        # Team context impact
        team_multiplier = 1.0
        if sleeper_player.team in [
            "KC",
            "BUF",
            "DAL",
            "SF",
            "PHI",
            "DET",
            "LAR",
            "BAL",
        ]:
            team_multiplier = 1.08  # Top tier offenses
        elif sleeper_player.team in ["MIA", "CIN", "HOU", "JAX", "LAC", "MIN", "ATL"]:
            team_multiplier = 1.02  # Good offenses
        elif sleeper_player.team in ["WAS", "CHI", "NYG", "CAR", "NYJ", "LV"]:
            team_multiplier = 0.92  # Struggling offenses

        # Add controlled variance based on player ID for consistency
        import random

        random.seed(hash(sleeper_player.sleeper_player_id) % 1000)
        variance = random.uniform(0.9, 1.1)

        # Calculate final value
        base_value = (min_val + max_val) / 2  # Use midpoint
        final_value = base_value * age_multiplier * team_multiplier * variance

        return round(final_value, 1)

    def _identify_position_needs(
        self, team_id: int, position_strengths: Dict, needs_analysis: Any
    ) -> Dict[str, int]:
        """Identify position needs (0-5 scale)"""
        position_needs = {}

        # Standard roster requirements
        standard_requirements = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}

        for position, min_strength in [("QB", 12), ("RB", 15), ("WR", 14), ("TE", 10)]:
            current_strength = position_strengths.get(position, 0)

            if current_strength < min_strength * 0.6:
                need_level = 5  # Critical need
            elif current_strength < min_strength * 0.8:
                need_level = 4  # High need
            elif current_strength < min_strength:
                need_level = 3  # Medium need
            elif current_strength < min_strength * 1.2:
                need_level = 2  # Slight need
            else:
                need_level = 1  # Depth need only

            position_needs[position] = need_level

        # Add needs from team analysis if available
        if needs_analysis and hasattr(needs_analysis, "position_needs"):
            stored_needs = needs_analysis.position_needs or {}
            for pos, need in stored_needs.items():
                position_needs[pos] = max(position_needs.get(pos, 0), need)

        return position_needs

    def _get_tradeable_players(
        self, team_id: int, roster_by_position: Dict
    ) -> Dict[str, List[Dict]]:
        """Identify players that could be traded away"""
        tradeable = {"surplus": [], "expendable": [], "valuable": []}

        for position, players in roster_by_position.items():
            if len(players) <= 1:
                continue  # Don't trade away only player at position

            # Sort players by value
            player_values = []
            for player in players:
                value = self._get_player_positional_value(player["id"], position)
                player_values.append((player, value))

            sorted_players = sorted(player_values, key=lambda x: x[1], reverse=True)

            # Categorize tradeable players
            if len(sorted_players) > 3:  # Surplus
                for player, value in sorted_players[3:]:
                    tradeable["surplus"].append({**player, "trade_value": value})

            if len(sorted_players) > 2:  # Expendable
                for player, value in sorted_players[2:3]:
                    tradeable["expendable"].append({**player, "trade_value": value})

            # Valuable players (could trade if getting great return)
            for player, value in sorted_players[:2]:
                if value >= 20:  # High-value players
                    tradeable["valuable"].append({**player, "trade_value": value})

        return tradeable

    def _get_tradeable_picks(
        self, team_id: int, league_id: int
    ) -> List[Dict[str, Any]]:
        """Get tradeable draft picks for team"""
        picks = (
            self.db.query(DraftPick)
            .filter(
                and_(
                    DraftPick.current_owner_team_id == team_id,
                    DraftPick.is_tradeable == True,
                )
            )
            .all()
        )

        tradeable_picks = []
        for pick in picks:
            pick_value = self._calculate_pick_trade_value(pick)
            tradeable_picks.append(
                {
                    "pick_id": pick.id,
                    "season": pick.season,
                    "round": pick.round_number,
                    "trade_value": pick_value,
                    "description": f"{pick.season} Round {pick.round_number}",
                }
            )

        return tradeable_picks

    def _calculate_pick_trade_value(self, pick: DraftPick) -> float:
        """Calculate trade value of a draft pick"""
        base_values = {1: 25.0, 2: 15.0, 3: 8.0, 4: 4.0}
        base_value = base_values.get(pick.round_number, 2.0)

        # Adjust for future years
        current_year = datetime.now().year
        years_out = pick.season - current_year
        if years_out > 0:
            base_value *= 0.9**years_out

        return base_value

    def _analyze_competitive_stance(
        self, team: FantasyTeam, league_id: int
    ) -> Dict[str, Any]:
        """Analyze team's competitive position and strategy"""
        # Get all teams for comparison
        all_teams = (
            self.db.query(FantasyTeam).filter(FantasyTeam.league_id == league_id).all()
        )

        # Try to get real data from Sleeper rosters first (current season for this user)
        # Find the most recent league for the user that matches this platform_league_id pattern
        sleeper_league = (
            self.db.query(SleeperLeague)
            .filter(SleeperLeague.sleeper_league_id == team.platform_league_id)
            .order_by(SleeperLeague.season.desc())
            .first()
        )

        if sleeper_league:
            sleeper_rosters = (
                self.db.query(SleeperRoster)
                .filter(SleeperRoster.league_id == sleeper_league.id)
                .all()
            )

            # Map fantasy teams to sleeper rosters
            team_stats = {}
            for roster in sleeper_rosters:
                fantasy_team = next(
                    (
                        t
                        for t in all_teams
                        if str(t.platform_team_id) == str(roster.sleeper_roster_id)
                    ),
                    None,
                )
                if fantasy_team:
                    team_stats[fantasy_team.id] = {
                        "wins": roster.wins or 0,
                        "losses": roster.losses or 0,
                        "points_for": roster.points_for or 0,
                    }

            # Use Sleeper data if available
            if team_stats:
                sorted_teams = sorted(
                    all_teams,
                    key=lambda t: (
                        -team_stats.get(t.id, {}).get("wins", 0),
                        -team_stats.get(t.id, {}).get("points_for", 0),
                    ),
                )
                team_rank = next(
                    i for i, t in enumerate(sorted_teams, 1) if t.id == team.id
                )
            else:
                # Fallback to database values
                sorted_teams = sorted(
                    all_teams, key=lambda t: (-t.wins, -float(t.points_for or 0))
                )
                team_rank = next(
                    i for i, t in enumerate(sorted_teams, 1) if t.id == team.id
                )
        else:
            # Fallback to database values
            sorted_teams = sorted(
                all_teams, key=lambda t: (-t.wins, -float(t.points_for or 0))
            )
            team_rank = next(
                i for i, t in enumerate(sorted_teams, 1) if t.id == team.id
            )

        total_teams = len(all_teams)
        playoff_cutoff = 6  # Default playoff teams

        return {
            "team_rank": team_rank,
            "total_teams": total_teams,
            "in_playoffs": team_rank <= playoff_cutoff,
            "playoff_bubble": playoff_cutoff < team_rank <= playoff_cutoff + 2,
            "rebuilding_candidate": team_rank > total_teams * 0.7,
            "championship_contender": team_rank <= 3,
            "competitive_tier": self._determine_competitive_tier(
                team_rank, total_teams
            ),
            "team_stats": (
                team_stats.get(team.id, {"wins": 0, "losses": 0, "points_for": 0})
                if "team_stats" in locals()
                else {"wins": 0, "losses": 0, "points_for": 0}
            ),
        }

    def _determine_competitive_tier(self, rank: int, total_teams: int) -> str:
        """Determine team's competitive tier"""
        if rank <= 3:
            return "championship"
        elif rank <= total_teams * 0.5:
            return "competitive"
        elif rank <= total_teams * 0.7:
            return "bubble"
        else:
            return "rebuild"

    def _identify_surplus_positions(self, position_strengths: Dict) -> List[str]:
        """Identify positions where team has surplus talent"""
        surplus = []

        # Thresholds for surplus (above average strength)
        surplus_thresholds = {"QB": 18, "RB": 22, "WR": 20, "TE": 15}

        for position, threshold in surplus_thresholds.items():
            if position_strengths.get(position, 0) > threshold:
                surplus.append(position)

        return surplus

    def _determine_trade_preferences(
        self, competitive_analysis: Dict
    ) -> Dict[str, Any]:
        """Determine what types of trades this team should pursue"""
        tier = competitive_analysis["competitive_tier"]

        if tier == "championship":
            return {
                "prefer_consolidation": True,
                "prefer_win_now": True,
                "accept_future_cost": True,
                "target_proven_players": True,
                "avoid_risk": True,
            }
        elif tier == "competitive":
            return {
                "prefer_consolidation": False,
                "prefer_win_now": True,
                "accept_future_cost": False,
                "target_proven_players": True,
                "avoid_risk": False,
            }
        elif tier == "bubble":
            return {
                "prefer_consolidation": False,
                "prefer_win_now": False,
                "accept_future_cost": False,
                "target_proven_players": False,
                "avoid_risk": False,
            }
        else:  # rebuild
            return {
                "prefer_consolidation": False,
                "prefer_win_now": False,
                "accept_future_cost": False,
                "target_proven_players": False,
                "avoid_risk": False,
                "prefer_youth": True,
                "prefer_picks": True,
            }

    # ============================================================================
    # TRADE SCENARIO GENERATION
    # ============================================================================

    def _generate_position_need_trades(
        self, team_context: Dict, league_context: Dict
    ) -> List[Dict[str, Any]]:
        """Generate trades to address positional needs"""
        recommendations = []

        # Get positions with high needs (4+ need level)
        critical_needs = {
            pos: need
            for pos, need in team_context["position_needs"].items()
            if need >= 4
        }

        for needed_position, need_level in critical_needs.items():
            # Find teams with surplus at this position
            potential_partners = self._find_teams_with_surplus(
                needed_position, team_context["team_id"], league_context["league_id"]
            )

            for partner_team_id, surplus_players in potential_partners.items():
                # Generate trade scenarios
                for player in surplus_players[:3]:  # Top 3 surplus players
                    trade_scenario = self._create_position_need_trade_scenario(
                        team_context,
                        partner_team_id,
                        needed_position,
                        player,
                        need_level,
                    )

                    if trade_scenario:
                        trade_scenario["recommendation_type"] = "position_need"
                        recommendations.append(trade_scenario)

        return recommendations

    def _generate_buy_low_trades(
        self, team_context: Dict, league_context: Dict
    ) -> List[Dict[str, Any]]:
        """Generate buy-low trade opportunities"""
        recommendations = []

        # Find buy-low candidates across the league
        buy_low_players = (
            self.db.query(FantasyPlayer)
            .join(PlayerTrends)
            .filter(
                and_(
                    PlayerTrends.buy_low_indicator == True,
                    PlayerTrends.season == league_context.get("season", 2025),
                )
            )
            .all()
        )

        for player in buy_low_players[:10]:  # Limit to top 10 candidates
            # Find which team owns this player
            owner_team = self._find_player_owner(player.id, league_context["league_id"])

            if owner_team and owner_team["team_id"] != team_context["team_id"]:
                trade_scenario = self._create_buy_low_trade_scenario(
                    team_context, owner_team, player, league_context
                )

                if trade_scenario:
                    trade_scenario["recommendation_type"] = "buy_low"
                    recommendations.append(trade_scenario)

        return recommendations

    def _generate_sell_high_trades(
        self, team_context: Dict, league_context: Dict
    ) -> List[Dict[str, Any]]:
        """Generate sell-high trade opportunities"""
        recommendations = []

        # Find sell-high candidates on our team
        team_players = [p["id"] for p in team_context["all_players"]]

        sell_high_players = (
            self.db.query(FantasyPlayer)
            .join(PlayerTrends)
            .filter(
                and_(
                    PlayerTrends.sell_high_indicator == True,
                    FantasyPlayer.id.in_(team_players),
                    PlayerTrends.season == league_context.get("season", 2025),
                )
            )
            .all()
        )

        for player in sell_high_players:
            # Find teams that might want this player
            interested_teams = self._find_teams_interested_in_player(
                player, league_context["league_id"], team_context["team_id"]
            )

            for team_id in interested_teams[:3]:  # Top 3 interested teams
                trade_scenario = self._create_sell_high_trade_scenario(
                    team_context, team_id, player, league_context
                )

                if trade_scenario:
                    trade_scenario["recommendation_type"] = "sell_high"
                    recommendations.append(trade_scenario)

        return recommendations

    def _generate_consolidation_trades(
        self, team_context: Dict, league_context: Dict
    ) -> List[Dict[str, Any]]:
        """Generate consolidation trades (2-for-1, 3-for-2, etc.)"""
        recommendations = []

        logger.info(
            f"Consolidation check - championship_contender: {team_context.get('competitive_analysis', {}).get('championship_contender', 'missing')}"
        )

        # Only for championship contenders - but let's be less restrictive for now
        competitive_analysis = team_context.get("competitive_analysis", {})
        if not competitive_analysis.get(
            "championship_contender", True
        ):  # Default to True for testing
            logger.info("Skipping consolidation - not a championship contender")
            return recommendations

        # Find positions with surplus depth
        surplus_positions = team_context.get("surplus_positions", [])
        logger.info(f"Surplus positions found: {surplus_positions}")

        tradeable_players = team_context.get("tradeable_players", {})
        logger.info(
            f"Tradeable players structure: {list(tradeable_players.keys()) if tradeable_players else 'None'}"
        )

        for position in surplus_positions:
            surplus_list = tradeable_players.get("surplus", [])
            expendable_list = tradeable_players.get("expendable", [])

            surplus_players = [
                p
                for p in surplus_list + expendable_list
                if p.get("position") == position
            ]
            logger.info(
                f"Found {len(surplus_players)} surplus/expendable {position} players"
            )

            if len(surplus_players) >= 2:
                # Find teams that need this position and have star players
                try:
                    trade_scenario = self._create_consolidation_trade_scenario(
                        team_context, position, surplus_players[:3], league_context
                    )

                    if trade_scenario:
                        trade_scenario["recommendation_type"] = "consolidation"
                        recommendations.append(trade_scenario)
                        logger.info(f"Created consolidation trade for {position}")
                    else:
                        logger.info(
                            f"Failed to create consolidation trade for {position}"
                        )
                except Exception as e:
                    logger.error(
                        f"Exception creating consolidation trade for {position}: {e}"
                    )
                    logger.info(f"Failed to create consolidation trade for {position}")

        return recommendations

    def _generate_depth_trades(
        self, team_context: Dict, league_context: Dict
    ) -> List[Dict[str, Any]]:
        """Generate trades to improve roster depth"""
        recommendations = []

        # Look for positions that need depth (need level 1-2)
        depth_needs = {
            pos: need
            for pos, need in team_context["position_needs"].items()
            if 1 <= need <= 2
        }

        for position, need_level in depth_needs.items():
            # Find teams with expendable players at this position
            depth_candidates = self._find_depth_candidates(
                position, team_context["team_id"], league_context["league_id"]
            )

            for candidate in depth_candidates[:5]:
                trade_scenario = self._create_depth_trade_scenario(
                    team_context, candidate, position, league_context
                )

                if trade_scenario:
                    trade_scenario["recommendation_type"] = "depth"
                    recommendations.append(trade_scenario)

        return recommendations

    # ============================================================================
    # TRADE SCENARIO CREATION HELPERS
    # ============================================================================

    def _create_position_need_trade_scenario(
        self,
        team_context: Dict,
        partner_team_id: int,
        position: str,
        target_player: Dict,
        need_level: int,
    ) -> Optional[Dict]:
        """Create a trade scenario for position need"""

        # Determine what we can offer
        offer_value = target_player["trade_value"]

        # Find appropriate return package
        return_package = self._find_appropriate_return_package(
            team_context, offer_value, exclude_positions=[position]
        )

        if not return_package:
            return None

        return {
            "target_team_id": partner_team_id,
            "we_get": {"players": [target_player["id"]], "picks": [], "faab": 0},
            "we_give": return_package,
            "trade_rationale": f"Address critical {position} need (level {need_level})",
            "target_player_info": target_player,
            "estimated_likelihood": self._estimate_acceptance_likelihood(
                offer_value, return_package, "position_need"
            ),
        }

    def _create_buy_low_trade_scenario(
        self,
        team_context: Dict,
        owner_team: Dict,
        player: FantasyPlayer,
        league_context: Dict,
    ) -> Optional[Dict]:
        """Create a buy-low trade scenario"""

        # Get player's current depressed value
        player_trend = (
            self.db.query(PlayerTrends)
            .filter(
                and_(
                    PlayerTrends.player_id == player.id,
                    PlayerTrends.buy_low_indicator == True,
                )
            )
            .first()
        )

        if not player_trend:
            return None

        # Estimate buy-low value (typically 70-85% of normal value)
        normal_value = self._get_player_positional_value(player.id, player.position)
        buy_low_value = normal_value * 0.8

        return_package = self._find_appropriate_return_package(
            team_context, buy_low_value
        )

        if not return_package:
            return None

        return {
            "target_team_id": owner_team["team_id"],
            "we_get": {"players": [player.id], "picks": [], "faab": 0},
            "we_give": return_package,
            "trade_rationale": f"Buy low on {player.name} - {player_trend.role_change_description or 'underperforming'}",
            "target_player_info": {
                "id": player.id,
                "name": player.name,
                "position": player.position,
                "normal_value": normal_value,
                "buy_low_value": buy_low_value,
            },
            "estimated_likelihood": self._estimate_acceptance_likelihood(
                buy_low_value, return_package, "buy_low"
            ),
        }

    def _create_sell_high_trade_scenario(
        self,
        team_context: Dict,
        target_team_id: int,
        player: FantasyPlayer,
        league_context: Dict,
    ) -> Optional[Dict]:
        """Create a sell-high trade scenario"""

        # Get player's inflated value
        normal_value = self._get_player_positional_value(player.id, player.position)
        sell_high_value = normal_value * 1.25  # 25% premium

        # Find what we can get in return
        target_package = self._find_target_return_package(
            target_team_id, sell_high_value, league_context["league_id"]
        )

        if not target_package:
            return None

        return {
            "target_team_id": target_team_id,
            "we_get": target_package,
            "we_give": {"players": [player.id], "picks": [], "faab": 0},
            "trade_rationale": f"Sell high on {player.name} - maximize value while hot",
            "target_player_info": {
                "id": player.id,
                "name": player.name,
                "position": player.position,
                "normal_value": normal_value,
                "sell_high_value": sell_high_value,
            },
            "estimated_likelihood": self._estimate_acceptance_likelihood(
                normal_value, target_package, "sell_high"
            ),
        }

    def _find_appropriate_return_package(
        self,
        team_context: Dict,
        target_value: float,
        exclude_positions: List[str] = None,
    ) -> Optional[Dict]:
        """Find appropriate return package from our assets"""
        exclude_positions = exclude_positions or []

        # Try single player first
        for category in ["expendable", "surplus", "valuable"]:
            for player in team_context["tradeable_players"][category]:
                if (
                    player["position"] not in exclude_positions
                    and abs(player["trade_value"] - target_value) <= target_value * 0.2
                ):
                    return {"players": [player["id"]], "picks": [], "faab": 0}

        # Try player + pick combinations
        for category in ["expendable", "surplus"]:
            for player in team_context["tradeable_players"][category]:
                if player["position"] not in exclude_positions:
                    remaining_value = target_value - player["trade_value"]

                    # Find matching pick
                    for pick in team_context["tradeable_picks"]:
                        if (
                            abs(pick["trade_value"] - remaining_value)
                            <= remaining_value * 0.3
                        ):
                            return {
                                "players": [player["id"]],
                                "picks": [pick["pick_id"]],
                                "faab": 0,
                            }

        # Try multiple players
        expendable_players = [
            p
            for p in team_context["tradeable_players"]["expendable"]
            + team_context["tradeable_players"]["surplus"]
            if p["position"] not in exclude_positions
        ]

        for combo in itertools.combinations(expendable_players, 2):
            combo_value = sum(p["trade_value"] for p in combo)
            if abs(combo_value - target_value) <= target_value * 0.15:
                return {"players": [p["id"] for p in combo], "picks": [], "faab": 0}

        return None

    def _find_target_return_package(
        self, target_team_id: int, desired_value: float, league_id: int
    ) -> Optional[Dict]:
        """Find what we want from target team"""
        target_context = self._get_comprehensive_team_context(target_team_id, league_id)

        # Look for players we'd want
        for category in ["valuable", "expendable"]:
            for player in target_context["tradeable_players"][category]:
                if abs(player["trade_value"] - desired_value) <= desired_value * 0.2:
                    return {"players": [player["id"]], "picks": [], "faab": 0}

        return None

    # ============================================================================
    # HELPER FUNCTIONS
    # ============================================================================

    def _find_teams_with_surplus(
        self, position: str, exclude_team_id: int, league_id: int
    ) -> Dict[int, List[Dict]]:
        """Find teams with surplus players at given position"""
        teams_with_surplus = {}

        # Get all teams in league except ours
        teams = (
            self.db.query(FantasyTeam)
            .filter(
                and_(
                    FantasyTeam.league_id == league_id,
                    FantasyTeam.id != exclude_team_id,
                )
            )
            .all()
        )

        for team in teams:
            team_context = self._get_comprehensive_team_context(team.id, league_id)

            # Check if they have surplus at this position
            surplus_players = [
                p
                for p in team_context["tradeable_players"]["surplus"]
                + team_context["tradeable_players"]["expendable"]
                if p["position"] == position
            ]

            if surplus_players:
                teams_with_surplus[team.id] = surplus_players

        return teams_with_surplus

    def _find_player_owner(self, player_id: int, league_id: int) -> Optional[Dict]:
        """Find which team owns a specific player"""
        roster_spot = (
            self.db.query(FantasyRosterSpot)
            .join(FantasyTeam)
            .filter(
                and_(
                    FantasyRosterSpot.player_id == player_id,
                    FantasyTeam.league_id == league_id,
                )
            )
            .first()
        )

        if roster_spot:
            return {"team_id": roster_spot.team_id, "team_name": roster_spot.team.name}
        return None

    def _find_teams_interested_in_player(
        self, player: FantasyPlayer, league_id: int, exclude_team_id: int
    ) -> List[int]:
        """Find teams that might be interested in acquiring a player"""
        interested_teams = []

        # Get all other teams
        teams = (
            self.db.query(FantasyTeam)
            .filter(
                and_(
                    FantasyTeam.league_id == league_id,
                    FantasyTeam.id != exclude_team_id,
                )
            )
            .all()
        )

        for team in teams:
            team_context = self._get_comprehensive_team_context(team.id, league_id)

            # Check if they need this position
            position_need = team_context["position_needs"].get(player.position, 0)

            if position_need >= 3:  # High need
                interested_teams.append(team.id)

        return interested_teams

    def _find_depth_candidates(
        self, position: str, exclude_team_id: int, league_id: int
    ) -> List[Dict]:
        """Find players available for depth trades"""
        candidates = []

        teams = (
            self.db.query(FantasyTeam)
            .filter(
                and_(
                    FantasyTeam.league_id == league_id,
                    FantasyTeam.id != exclude_team_id,
                )
            )
            .all()
        )

        for team in teams:
            team_context = self._get_comprehensive_team_context(team.id, league_id)

            # Get expendable players at this position
            expendable = [
                p
                for p in team_context["tradeable_players"]["expendable"]
                if p["position"] == position and p["trade_value"] <= 15
            ]

            for player in expendable:
                candidates.append({**player, "owner_team_id": team.id})

        return candidates

    def _estimate_acceptance_likelihood(
        self, offered_value: float, return_package: Dict, trade_type: str
    ) -> float:
        """Estimate likelihood of trade acceptance"""
        base_likelihood = 0.4  # 40% base

        # Adjust based on trade type
        type_adjustments = {
            "position_need": 0.1,  # +10% for addressing needs
            "buy_low": -0.1,  # -10% for buy-low attempts
            "sell_high": -0.15,  # -15% for sell-high attempts
            "consolidation": 0.05,  # +5% for fair consolidation
            "depth": 0.15,  # +15% for depth trades
        }

        base_likelihood += type_adjustments.get(trade_type, 0)

        # Adjust based on value fairness
        package_value = sum(
            self._get_simple_player_value(pid)
            for pid in return_package.get("players", [])
        )
        value_ratio = package_value / offered_value if offered_value > 0 else 1.0

        if 0.9 <= value_ratio <= 1.1:
            base_likelihood += 0.2  # Fair trade bonus
        elif value_ratio > 1.2:
            base_likelihood += 0.3  # Overpay bonus
        elif value_ratio < 0.8:
            base_likelihood -= 0.3  # Underpay penalty

        return round(max(0.05, min(0.95, base_likelihood)), 2)

    def _get_simple_player_value(self, player_id: int) -> float:
        """Get simple player value for calculations"""
        player_value = (
            self.db.query(PlayerValue)
            .filter(PlayerValue.player_id == player_id)
            .order_by(desc(PlayerValue.week))
            .first()
        )

        if player_value and player_value.rest_of_season_value:
            return player_value.rest_of_season_value

        # Fallback to Sleeper player data for realistic values
        from app.models.database_models import SleeperPlayer

        sleeper_player = (
            self.db.query(SleeperPlayer)
            .filter(SleeperPlayer.sleeper_player_id == str(player_id))
            .first()
        )

        if sleeper_player:
            return self._calculate_realistic_player_value(sleeper_player)

        return 20.0

    # ============================================================================
    # RECOMMENDATION SCORING AND RANKING
    # ============================================================================

    def _score_and_rank_recommendations(
        self, recommendations: List[Dict], team_context: Dict, league_context: Dict
    ) -> List[Dict]:
        """Score and rank all recommendations"""

        for rec in recommendations:
            score = self._calculate_recommendation_score(
                rec, team_context, league_context
            )
            rec["priority_score"] = score

        # Sort by priority score descending
        return sorted(recommendations, key=lambda x: x["priority_score"], reverse=True)

    def _calculate_recommendation_score(
        self, recommendation: Dict, team_context: Dict, league_context: Dict
    ) -> float:
        """Calculate priority score for recommendation"""
        score = 0.0

        # Base score from likelihood
        score += recommendation.get("estimated_likelihood", 0.4) * 30

        # Bonus for addressing high needs
        rec_type = recommendation.get("recommendation_type", "")
        if rec_type == "position_need":
            score += 25
        elif rec_type == "buy_low":
            score += 20
        elif rec_type == "consolidation":
            if team_context["competitive_analysis"]["championship_contender"]:
                score += 20

        # Team strategy alignment
        trade_prefs = team_context["trade_preferences"]

        if rec_type == "consolidation" and trade_prefs.get("prefer_consolidation"):
            score += 15
        elif rec_type in ["buy_low", "depth"] and not trade_prefs.get("prefer_win_now"):
            score += 10

        # Time sensitivity
        if league_context["trade_deadline_weeks"] <= 3:
            if rec_type in ["position_need", "consolidation"]:
                score += 10  # Deadline urgency

        return round(score, 1)

    def _filter_viable_recommendations(self, recommendations: List[Dict]) -> List[Dict]:
        """Filter for viable recommendations"""
        viable = []

        for rec in recommendations:
            # Minimum likelihood threshold
            if rec.get("estimated_likelihood", 0) < 0.2:
                continue

            # Minimum priority score
            if rec.get("priority_score", 0) < 15:
                continue

            viable.append(rec)

        return viable

    def _store_recommendations(
        self, team_id: int, league_id: int, recommendations: List[Dict]
    ):
        """Store recommendations in database"""
        try:
            # Clear existing recommendations for this team
            self.db.query(TradeRecommendation).filter(
                and_(
                    TradeRecommendation.requesting_team_id == team_id,
                    TradeRecommendation.is_active == True,
                )
            ).update({"is_active": False})

            # Store new recommendations
            for rec in recommendations:
                trade_rec = TradeRecommendation(
                    league_id=league_id,
                    requesting_team_id=team_id,
                    target_team_id=rec["target_team_id"],
                    recommendation_type=rec.get("recommendation_type", "general"),
                    priority_score=rec.get("priority_score", 0),
                    suggested_trade={
                        "requesting_team_gives": rec["we_give"],
                        "requesting_team_gets": rec["we_get"],
                    },
                    mutual_benefit_score=rec.get("mutual_benefit_score", 0),
                    likelihood_accepted=rec.get("estimated_likelihood", 0),
                    recommendation_reason=rec.get("trade_rationale", ""),
                    timing_factor=f"Generated for week 8",
                    expires_at=datetime.utcnow() + timedelta(days=7),
                )

                self.db.add(trade_rec)

            self.db.commit()

        except Exception as e:
            logger.error(f"Failed to store recommendations: {str(e)}")
            self.db.rollback()

    # ============================================================================
    # BILATERAL TRADE ANALYSIS
    # ============================================================================

    def _generate_bilateral_trade_scenarios(
        self, team1_context: Dict, team2_context: Dict, league_context: Dict
    ) -> List[Dict[str, Any]]:
        """Generate potential trades between two specific teams"""
        scenarios = []

        # Analyze what each team needs and can offer
        team1_needs = team1_context["position_needs"]
        team2_needs = team2_context["position_needs"]

        team1_surplus = team1_context["surplus_positions"]
        team2_surplus = team2_context["surplus_positions"]

        # Find complementary needs (team1 needs what team2 has surplus of)
        complementary_positions = []

        for pos in team1_needs:
            if team1_needs[pos] >= 3 and pos in team2_surplus:
                complementary_positions.append((pos, "team1_needs", "team2_has"))

        for pos in team2_needs:
            if team2_needs[pos] >= 3 and pos in team1_surplus:
                complementary_positions.append((pos, "team2_needs", "team1_has"))

        # Generate specific trade scenarios
        for position, needing_team, surplus_team in complementary_positions:
            scenario = self._create_bilateral_scenario(
                team1_context, team2_context, position, needing_team, surplus_team
            )

            if scenario:
                scenarios.append(scenario)

        return scenarios

    def _create_bilateral_scenario(
        self,
        team1_context: Dict,
        team2_context: Dict,
        position: str,
        needing_team: str,
        surplus_team: str,
    ) -> Optional[Dict]:
        """Create specific bilateral trade scenario"""

        if needing_team == "team1_needs":
            receiving_context = team1_context
            giving_context = team2_context
        else:
            receiving_context = team2_context
            giving_context = team1_context

        # Find suitable player to trade
        available_players = [
            p
            for p in giving_context["tradeable_players"]["surplus"]
            + giving_context["tradeable_players"]["expendable"]
            if p["position"] == position
        ]

        if not available_players:
            return None

        target_player = max(available_players, key=lambda p: p["trade_value"])

        # Find return package
        return_package = self._find_appropriate_return_package(
            receiving_context,
            target_player["trade_value"],
            exclude_positions=[position],
        )

        if not return_package:
            return None

        return {
            "team1_gives": (
                return_package
                if needing_team == "team1_needs"
                else {"players": [target_player["id"]], "picks": [], "faab": 0}
            ),
            "team1_gets": (
                {"players": [target_player["id"]], "picks": [], "faab": 0}
                if needing_team == "team1_needs"
                else return_package
            ),
            "team2_gives": (
                {"players": [target_player["id"]], "picks": [], "faab": 0}
                if needing_team == "team1_needs"
                else return_package
            ),
            "team2_gets": (
                return_package
                if needing_team == "team1_needs"
                else {"players": [target_player["id"]], "picks": [], "faab": 0}
            ),
            "primary_position": position,
            "addresses_need": True,
            "target_player": target_player,
        }

    def _evaluate_mutual_benefit(
        self,
        scenario: Dict,
        team1_context: Dict,
        team2_context: Dict,
        league_context: Dict,
    ) -> Dict[str, Any]:
        """Evaluate whether trade is mutually beneficial"""

        # Calculate benefit for each team
        team1_benefit = self._calculate_team_benefit(
            scenario["team1_gives"],
            scenario["team1_gets"],
            team1_context,
            league_context,
        )

        team2_benefit = self._calculate_team_benefit(
            scenario["team2_gives"],
            scenario["team2_gets"],
            team2_context,
            league_context,
        )

        # Determine if mutually beneficial
        is_beneficial = (
            team1_benefit["net_benefit"] > 0 and team2_benefit["net_benefit"] > 0
        )

        # Calculate combined benefit score
        combined_score = (
            team1_benefit["net_benefit"] + team2_benefit["net_benefit"]
        ) / 2

        return {
            "is_mutually_beneficial": is_beneficial,
            "benefit_score": round(combined_score, 2),
            "team1_benefit": team1_benefit,
            "team2_benefit": team2_benefit,
            "fairness_assessment": (
                "Fair"
                if abs(team1_benefit["net_benefit"] - team2_benefit["net_benefit"]) <= 2
                else "Uneven"
            ),
        }

    def _calculate_team_benefit(
        self, gives: Dict, gets: Dict, team_context: Dict, league_context: Dict
    ) -> Dict[str, Any]:
        """Calculate benefit for one team in a trade"""

        # Calculate value given up
        value_given = 0.0
        for player_id in gives.get("players", []):
            value_given += self._get_simple_player_value(player_id)

        # Calculate value received
        value_received = 0.0
        for player_id in gets.get("players", []):
            value_received += self._get_simple_player_value(player_id)

        # Calculate positional impact
        positional_impact = self._calculate_positional_benefit(
            gives, gets, team_context
        )

        # Calculate strategic alignment
        strategic_benefit = self._calculate_strategic_benefit(gives, gets, team_context)

        # Net benefit calculation
        net_benefit = (
            (value_received - value_given) + positional_impact + strategic_benefit
        )

        return {
            "value_given": round(value_given, 2),
            "value_received": round(value_received, 2),
            "positional_impact": round(positional_impact, 2),
            "strategic_benefit": round(strategic_benefit, 2),
            "net_benefit": round(net_benefit, 2),
        }

    def _calculate_positional_benefit(
        self, gives: Dict, gets: Dict, team_context: Dict
    ) -> float:
        """Calculate positional impact benefit"""
        benefit = 0.0

        # Check positions we're getting
        for player_id in gets.get("players", []):
            player = (
                self.db.query(FantasyPlayer)
                .filter(FantasyPlayer.id == player_id)
                .first()
            )
            if player:
                position_need = team_context["position_needs"].get(player.position, 0)
                if position_need >= 4:
                    benefit += 5.0  # High need fulfillment
                elif position_need >= 2:
                    benefit += 2.0  # Medium need fulfillment

        return benefit

    def _calculate_strategic_benefit(
        self, gives: Dict, gets: Dict, team_context: Dict
    ) -> float:
        """Calculate strategic alignment benefit"""
        benefit = 0.0
        trade_prefs = team_context["trade_preferences"]

        # Consolidation benefit (getting fewer, better players)
        players_in = len(gets.get("players", []))
        players_out = len(gives.get("players", []))

        if players_out > players_in and trade_prefs.get("prefer_consolidation"):
            benefit += 3.0

        # Future vs present focus
        if trade_prefs.get("prefer_picks") and gets.get("picks"):
            benefit += 2.0

        return benefit

    def _get_sleeper_roster_for_team(self, team_id: int) -> Optional[Dict[str, Any]]:
        """Get Sleeper roster data for a fantasy team as fallback"""
        try:
            # First get the fantasy team to find its platform_team_id and league
            from app.models.fantasy_models import FantasyTeam, FantasyLeague

            fantasy_team = (
                self.db.query(FantasyTeam).filter(FantasyTeam.id == team_id).first()
            )
            if not fantasy_team:
                logger.info(f"Fantasy team {team_id} not found")
                return None

            # Get the fantasy league to find the correct season
            fantasy_league = (
                self.db.query(FantasyLeague)
                .filter(FantasyLeague.id == fantasy_team.league_id)
                .first()
            )
            if not fantasy_league:
                logger.info(f"Fantasy league {fantasy_team.league_id} not found")
                return None

            # Find the corresponding SleeperLeague for the most recent season
            sleeper_league = (
                self.db.query(SleeperLeague)
                .filter(
                    SleeperLeague.sleeper_league_id == fantasy_league.platform_league_id
                )
                .order_by(SleeperLeague.season.desc())
                .first()
            )

            if not sleeper_league:
                logger.info(
                    f"Sleeper league {fantasy_league.platform_league_id} not found"
                )
                return None

            # Find corresponding SleeperRoster using the correct league and roster ID
            sleeper_roster = (
                self.db.query(SleeperRoster)
                .filter(
                    SleeperRoster.league_id == sleeper_league.id,
                    SleeperRoster.sleeper_roster_id
                    == str(fantasy_team.platform_team_id),
                )
                .first()
            )

            if not sleeper_roster or not sleeper_roster.players:
                return None

            logger.info(
                f"Found Sleeper roster {sleeper_roster.id} with {len(sleeper_roster.players)} players"
            )

            # Convert player IDs to player data with proper name lookup
            players_data = []
            for player_id in sleeper_roster.players:
                # Look up player details from SleeperPlayer table
                sleeper_player = (
                    self.db.query(SleeperPlayer)
                    .filter(SleeperPlayer.sleeper_player_id == str(player_id))
                    .first()
                )

                if sleeper_player:
                    # Use actual player data - prefer full_name, fallback to first + last
                    player_name = (
                        sleeper_player.full_name
                        or f"{sleeper_player.first_name or ''} {sleeper_player.last_name or ''}".strip()
                    )
                    if not player_name or player_name.isspace():
                        player_name = f"Player {player_id}"

                    player_data = {
                        "id": (
                            int(player_id) if player_id.isdigit() else hash(player_id)
                        ),
                        "name": player_name,
                        "position": sleeper_player.position or "Unknown",
                        "team": sleeper_player.team or "Unknown",
                        "age": sleeper_player.age or 0,
                    }
                else:
                    # Fallback for missing player data
                    player_data = {
                        "id": (
                            int(player_id) if player_id.isdigit() else hash(player_id)
                        ),
                        "name": f"Player {player_id}",
                        "position": self._guess_position_from_id(player_id),
                        "team": "NFL",
                        "age": 27,  # Default age
                    }
                players_data.append(player_data)

            return {
                "roster_id": sleeper_roster.id,
                "team_name": sleeper_roster.team_name or f"Team {team_id}",
                "owner_name": sleeper_roster.owner_name or "Unknown",
                "players": players_data,
            }

        except Exception as e:
            logger.error(f"Failed to get Sleeper roster for team {team_id}: {str(e)}")
            return None

    def _guess_position_from_id(self, player_id: str) -> str:
        """Guess player position from ID (fallback method)"""
        # Simple heuristic - in production, you'd look this up properly
        if not player_id.isdigit():
            return "DEF"  # Defense/kicker teams

        id_hash = hash(player_id) % 6
        positions = [
            "QB",
            "RB",
            "RB",
            "WR",
            "WR",
            "TE",
        ]  # Weight toward skill positions
        return positions[id_hash]

    def _calculate_player_trade_value(self, player: Dict) -> float:
        """Calculate trade value for a player using same logic as trade analyzer"""
        position = player.get("position", "Unknown")
        age = player.get("age", 27)
        team = player.get("team", "")

        # Base values by position
        base_values = {
            "QB": 25.0,
            "RB": 22.0,
            "WR": 20.0,
            "TE": 15.0,
            "K": 3.0,
            "DEF": 5.0,
        }
        base_value = base_values.get(position, 12.0)

        # Age adjustments
        if age and age <= 24:
            age_multiplier = 1.2
        elif age and age <= 27:
            age_multiplier = 1.1
        elif age and age <= 30:
            age_multiplier = 1.0
        else:
            age_multiplier = 0.8

        # Team quality adjustments (simplified)
        top_teams = ["BUF", "KC", "DAL", "SF", "PHI", "MIA"]
        if team in top_teams:
            team_multiplier = 1.1
        else:
            team_multiplier = 1.0

        # Add some variance
        import random

        variance = random.uniform(0.8, 1.2)

        return round(base_value * age_multiplier * team_multiplier * variance, 1)

    def _create_consolidation_trade_scenario(
        self,
        team_context: Dict,
        position: str,
        surplus_players: List[Dict],
        league_context: Dict,
    ) -> Optional[Dict]:
        """Create a consolidation trade scenario (2-for-1, 3-for-2)"""
        try:
            logger.info(
                f"Creating consolidation scenario for {position} with {len(surplus_players)} players"
            )

            # Find teams that need this position and have star players
            total_value = sum(p.get("trade_value", 20) for p in surplus_players)
            logger.info(f"Total surplus player value: {total_value}")

            # Look for star players worth 50-70% of our combined value (more realistic for consolidation)
            target_value_min = total_value * 0.5
            target_value_max = total_value * 0.7
            logger.info(
                f"Looking for target players valued between {target_value_min:.1f} and {target_value_max:.1f}"
            )

            # Find actual star players from other teams at this position
            league_id = int(
                league_context["league_id"]
            )  # Convert to int for database query

            # Get all teams except our own
            other_teams = (
                self.db.query(FantasyTeam)
                .filter(
                    and_(
                        FantasyTeam.league_id == league_id,
                        FantasyTeam.id != team_context["team_id"],
                    )
                )
                .all()
            )

            logger.info(
                f"Checking {len(other_teams)} other teams for {position} targets"
            )

            best_target = None
            best_partner_team_id = None

            for other_team in other_teams:
                logger.info(f"Checking team {other_team.id} for {position} players")
                # Get their roster using Sleeper data
                partner_roster = self._get_sleeper_roster_for_team(other_team.id)
                if not partner_roster or not partner_roster.get("players"):
                    logger.info(f"No roster found for team {other_team.id}")
                    continue

                # Find their best player at this position
                position_players = [
                    p
                    for p in partner_roster["players"]
                    if p.get("position") == position
                ]
                logger.info(
                    f"Team {other_team.id} has {len(position_players)} {position} players"
                )

                for player in position_players:
                    # Calculate trade value for their player using same logic as ours
                    player_value = self._calculate_player_trade_value(player)
                    logger.info(
                        f"Player {player.get('full_name', player.get('name', 'Unknown'))} ({position}) value: {player_value}"
                    )

                    if target_value_min <= player_value <= target_value_max:
                        if not best_target or player_value > best_target.get(
                            "trade_value", 0
                        ):
                            best_target = player.copy()
                            best_target["trade_value"] = player_value
                            best_partner_team_id = other_team.id
                            logger.info(
                                f"New best target: {player.get('full_name', player.get('name', 'Unknown'))} (value: {player_value})"
                            )

            if not best_target:
                logger.info(
                    f"No suitable {position} target found in value range {target_value_min:.1f}-{target_value_max:.1f}"
                )
                return None

            logger.info(
                f"Creating consolidation trade: {len(surplus_players)} players for {best_target.get('name')}"
            )

            return {
                "target_team_id": best_partner_team_id,
                "we_get": {"players": [best_target], "picks": [], "faab": 0},
                "we_give": {"players": surplus_players, "picks": [], "faab": 0},
                "trade_rationale": f"Consolidate {len(surplus_players)} {position} players into one elite starter",
                "estimated_likelihood": 0.6,
            }
        except Exception as e:
            logger.error(f"Error creating consolidation scenario: {str(e)}")
            return None

    def _create_depth_trade_scenario(
        self,
        team_context: Dict,
        needed_position: str,
        target_player: Dict,
        target_team_id: int,
    ) -> Optional[Dict]:
        """Create a depth trade scenario"""
        try:
            # Depth trades are typically smaller value exchanges
            offer_value = target_player.get("trade_value", 15)

            # Find appropriate return package from our surplus
            return_package = self._find_appropriate_return_package(
                team_context, offer_value, exclude_positions=[]
            )

            if not return_package:
                return None

            return {
                "target_team_id": target_team_id,
                "we_get": {"players": [target_player["id"]], "picks": [], "faab": 0},
                "we_give": return_package,
                "trade_rationale": f"Add {needed_position} depth for roster flexibility",
                "target_player_info": target_player,
                "estimated_likelihood": 0.7,
            }
        except Exception as e:
            logger.error(f"Error creating depth scenario: {str(e)}")
            return None
