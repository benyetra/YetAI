"""
Unified Bet Verification Service - THE ONLY SERVICE FOR BET VERIFICATION

⚠️ IMPORTANT: This is the ONLY bet verification service that should be used.
   The old bet_verification_service.py has been deprecated.

This service works with the SimpleUnifiedBet model and uses The Odds API for verification:
1. Fetches pending bets from simple_unified_bets table
2. Uses odds_api_event_id to get game results from The Odds API
3. Determines bet outcomes based on real API data using stored enums (no string parsing)
4. Updates bet statuses and calculates payouts
5. Handles individual bets, parlays, and live bets uniformly

Key improvements over old service:
- No string parsing for bet outcomes (uses TeamSide, OverUnder enums set during bet creation)
- Matches scores by team name, not array position
- Uses explicit 'completed' boolean from Odds API
- Spread values include +/- sign for proper calculation
- All status comparisons use BetStatus enum
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from app.core.database import SessionLocal
from app.models.simple_unified_bet_model import SimpleUnifiedBet, TeamSide, OverUnder
from app.models.database_models import BetStatus, BetType
from app.services.optimized_odds_api_service import get_optimized_odds_service
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class UnifiedBetResult:
    """Result of evaluating a unified bet"""

    bet_id: str
    status: BetStatus
    result_amount: float
    reasoning: str


class UnifiedBetVerificationService:
    """Unified bet verification service for simple_unified_bets table"""

    def __init__(self):
        self.odds_service = get_optimized_odds_service(settings.ODDS_API_KEY)

    async def verify_all_pending_bets(self) -> Dict:
        """
        Main method to verify all pending bets in the unified table
        """
        start_time = datetime.now()
        logger.info("🎯 Starting unified bet verification...")

        db = SessionLocal()
        try:
            # Debug: Check all bets first
            all_bets = db.query(SimpleUnifiedBet).all()
            logger.info(f"Total bets in unified table: {len(all_bets)}")

            for bet in all_bets[:3]:  # Log first 3 for debugging
                logger.info(
                    f"Bet {bet.id[:8]}: status={bet.status} ({type(bet.status)}) - {bet.selection}"
                )

            # Get all pending bets from unified table
            pending_bets = (
                db.query(SimpleUnifiedBet)
                .filter(SimpleUnifiedBet.status == BetStatus.PENDING)
                .all()
            )

            logger.info(f"Found {len(pending_bets)} pending bets to verify")

            if not pending_bets:
                return {
                    "success": True,
                    "message": "No pending bets",
                    "verified": 0,
                    "settled": 0,
                }

            # Group bets by sport for efficient API calls
            bets_by_sport = {}
            for bet in pending_bets:
                sport = bet.sport.lower() if bet.sport else "unknown"
                if sport not in bets_by_sport:
                    bets_by_sport[sport] = []
                bets_by_sport[sport].append(bet)

            # Get game results for each sport
            all_results = []
            total_verified = 0
            total_settled = 0

            for sport, sport_bets in bets_by_sport.items():
                if sport == "unknown":
                    logger.warning(
                        f"Skipping {len(sport_bets)} bets with unknown sport"
                    )
                    continue

                # Handle parlay parent bets separately (they check leg statuses, not game results)
                if sport == "multiple sports":
                    logger.info(
                        f"Verifying {len(sport_bets)} parlay parent bets based on leg statuses..."
                    )
                    parlay_results = []
                    for parlay_bet in sport_bets:
                        try:
                            status, result_amount, reasoning = self._evaluate_parlay(
                                parlay_bet
                            )
                            if status != BetStatus.PENDING:
                                parlay_results.append(
                                    UnifiedBetResult(
                                        bet_id=parlay_bet.id,
                                        status=status,
                                        result_amount=result_amount,
                                        reasoning=reasoning,
                                    )
                                )
                                logger.info(
                                    f"Parlay {parlay_bet.id}: {status.value} - {reasoning}"
                                )
                        except Exception as e:
                            logger.error(
                                f"Error evaluating parlay {parlay_bet.id}: {e}"
                            )

                    all_results.extend(parlay_results)
                    continue

                try:
                    logger.info(f"Verifying {len(sport_bets)} {sport.upper()} bets...")

                    # Get completed games for this sport (last 3 days)
                    normalized_sport = self._normalize_sport(sport)
                    completed_games = await self.odds_service.get_scores_optimized(
                        normalized_sport, include_completed=True
                    )

                    logger.info(
                        f"Retrieved {len(completed_games)} game results for {sport}"
                    )

                    # Process each bet for this sport
                    for bet in sport_bets:
                        result = await self._verify_single_bet(bet, completed_games)
                        if result:
                            all_results.append(result)
                            total_verified += 1
                            if result.status != BetStatus.PENDING:
                                total_settled += 1

                except Exception as e:
                    logger.error(f"Error verifying {sport} bets: {e}")
                    continue

            # Apply results to database
            if all_results:
                await self._apply_results(all_results, db)

            db.commit()

            duration = (datetime.now() - start_time).total_seconds()
            logger.info(
                f"✅ Unified verification complete: {total_settled} settled, {total_verified} verified in {duration:.1f}s"
            )

            return {
                "success": True,
                "message": f"Verified {total_verified} bets, settled {total_settled}",
                "verified": total_verified,
                "settled": total_settled,
                "duration": duration,
            }

        except Exception as e:
            logger.error(f"Error in unified bet verification: {e}")
            db.rollback()
            return {
                "success": False,
                "error": str(e),
                "verified": 0,
                "settled": 0,
            }
        finally:
            db.close()

    async def _verify_single_bet(
        self, bet: SimpleUnifiedBet, completed_games: List[Dict]
    ) -> Optional[UnifiedBetResult]:
        """Verify a single bet against completed games"""

        # Find the game by odds_api_event_id
        game_data = None
        for game in completed_games:
            if game.get("id") == bet.odds_api_event_id:
                game_data = game
                break

        if not game_data:
            logger.debug(
                f"Game {bet.odds_api_event_id[:8]} not found in completed games"
            )
            return None

        # Check if game is completed using the completed boolean field from Odds API
        is_completed = game_data.get("completed")
        if not is_completed:
            logger.debug(
                f"Game {bet.odds_api_event_id[:8]} not yet completed "
                f"(completed={is_completed})"
            )
            return None

        # Get final scores - match by team name, not array index
        scores = game_data.get("scores")
        if not scores or len(scores) < 2:
            logger.warning(f"Invalid scores for game {bet.odds_api_event_id[:8]}")
            return None

        # Match scores to home/away teams by name
        home_score = None
        away_score = None

        for score_entry in scores:
            team_name = score_entry.get("name", "")
            score_value = score_entry.get("score")

            # Match against bet's stored team names
            if team_name == bet.home_team:
                home_score = int(score_value) if score_value is not None else 0
            elif team_name == bet.away_team:
                away_score = int(score_value) if score_value is not None else 0

        # Verify we found both scores
        if home_score is None or away_score is None:
            logger.warning(
                f"Could not match scores to teams for game {bet.odds_api_event_id[:8]}. "
                f"Expected teams: {bet.home_team} vs {bet.away_team}. "
                f"API teams: {[s.get('name') for s in scores]}"
            )
            return None

        logger.info(
            f"Verifying bet {bet.id[:8]}: {bet.bet_type.value} - {bet.selection}"
        )
        logger.info(
            f"Final score: {bet.away_team} {away_score} - {bet.home_team} {home_score}"
        )

        # Determine bet outcome
        return self._evaluate_bet_outcome(bet, home_score, away_score)

    def _evaluate_bet_outcome(
        self, bet: SimpleUnifiedBet, home_score: int, away_score: int
    ) -> UnifiedBetResult:
        """Evaluate bet outcome based on scores"""

        bet_type = bet.bet_type
        status = BetStatus.LOST
        result_amount = 0.0
        reasoning = ""

        try:
            if bet_type == BetType.MONEYLINE:
                status, result_amount, reasoning = self._evaluate_moneyline(
                    bet, home_score, away_score
                )
            elif bet_type == BetType.SPREAD:
                status, result_amount, reasoning = self._evaluate_spread(
                    bet, home_score, away_score
                )
            elif bet_type == BetType.TOTAL:
                status, result_amount, reasoning = self._evaluate_total(
                    bet, home_score, away_score
                )
            elif bet_type == BetType.PARLAY:
                # Handle parlay bets (check all legs)
                status, result_amount, reasoning = self._evaluate_parlay(bet)
            elif bet_type == BetType.PROP:
                # Player props use sport-specific APIs for verification
                logger.info(
                    f"Bet {bet.id[:8]}: Player prop bet - verifying with sport-specific API"
                )
                # Import here to avoid circular dependency
                from app.services.player_prop_verification_service import (
                    PlayerPropVerificationService,
                )

                # Verify the prop bet using sport-specific service
                prop_service = PlayerPropVerificationService(self.db)
                prop_result = await prop_service.verify_single_prop(bet)

                if prop_result:
                    status = prop_result["status"]
                    result_amount = prop_result.get("result_amount", 0.0)
                    reasoning = prop_result.get("reasoning", "Prop verified via API")
                else:
                    # Could not verify yet (game not complete or API error)
                    return None
            else:
                reasoning = f"Unknown bet type: {bet_type}"
                logger.warning(reasoning)

        except Exception as e:
            logger.error(f"Error evaluating bet {bet.id[:8]}: {e}")
            reasoning = f"Evaluation error: {str(e)}"

        return UnifiedBetResult(
            bet_id=bet.id,
            status=status,
            result_amount=result_amount,
            reasoning=reasoning,
        )

    def _evaluate_moneyline(
        self, bet: SimpleUnifiedBet, home_score: int, away_score: int
    ) -> Tuple[BetStatus, float, str]:
        """Evaluate moneyline bet using stored team_selection enum"""

        if home_score == away_score:
            return BetStatus.PUSHED, bet.amount, "Game tied - bet pushed"

        # Determine actual winner
        actual_winner = TeamSide.HOME if home_score > away_score else TeamSide.AWAY

        # Use stored team_selection enum (set during bet creation)
        if bet.team_selection == actual_winner:
            payout = bet.amount + bet.potential_win
            return (
                BetStatus.WON,
                payout,
                f"Won: {bet.selected_team_name} won ({home_score}-{away_score})",
            )
        else:
            return (
                BetStatus.LOST,
                0.0,
                f"Lost: {bet.selected_team_name} lost ({home_score}-{away_score})",
            )

    def _evaluate_spread(
        self, bet: SimpleUnifiedBet, home_score: int, away_score: int
    ) -> Tuple[BetStatus, float, str]:
        """Evaluate spread bet using stored spread_selection enum and spread_value with +/- sign"""

        if not bet.spread_value:
            return BetStatus.LOST, 0.0, "Invalid spread value"

        # spread_value already includes +/- sign (e.g., -7.5 or +3.5)
        spread = bet.spread_value

        # Apply spread to selected team (spread already has correct sign)
        if bet.spread_selection == TeamSide.HOME:
            adjusted_home = home_score + spread
            if adjusted_home > away_score:
                payout = bet.amount + bet.potential_win
                return (
                    BetStatus.WON,
                    payout,
                    f"Won: {bet.selected_team_name} {spread:+.1f} covered "
                    f"({adjusted_home:.1f} vs {away_score})",
                )
            elif adjusted_home == away_score:
                return (
                    BetStatus.PUSHED,
                    bet.amount,
                    f"Push: {bet.selected_team_name} {spread:+.1f} tied",
                )
            else:
                return (
                    BetStatus.LOST,
                    0.0,
                    f"Lost: {bet.selected_team_name} {spread:+.1f} didn't cover "
                    f"({adjusted_home:.1f} vs {away_score})",
                )
        else:  # AWAY
            adjusted_away = away_score + spread
            if adjusted_away > home_score:
                payout = bet.amount + bet.potential_win
                return (
                    BetStatus.WON,
                    payout,
                    f"Won: {bet.selected_team_name} {spread:+.1f} covered "
                    f"({adjusted_away:.1f} vs {home_score})",
                )
            elif adjusted_away == home_score:
                return (
                    BetStatus.PUSHED,
                    bet.amount,
                    f"Push: {bet.selected_team_name} {spread:+.1f} tied",
                )
            else:
                return (
                    BetStatus.LOST,
                    0.0,
                    f"Lost: {bet.selected_team_name} {spread:+.1f} didn't cover "
                    f"({adjusted_away:.1f} vs {home_score})",
                )

    def _evaluate_total(
        self, bet: SimpleUnifiedBet, home_score: int, away_score: int
    ) -> Tuple[BetStatus, float, str]:
        """Evaluate total (over/under) bet using stored over_under_selection enum"""

        if not bet.total_points:
            return BetStatus.LOST, 0.0, "Invalid total points value"

        total_score = home_score + away_score
        line = bet.total_points

        # Use stored over_under_selection enum (set during bet creation)
        is_over = bet.over_under_selection == OverUnder.OVER

        if total_score == line:
            return BetStatus.PUSHED, bet.amount, f"Push: Total exactly {line}"
        elif (is_over and total_score > line) or (not is_over and total_score < line):
            payout = bet.amount + bet.potential_win
            direction = "Over" if is_over else "Under"
            return (
                BetStatus.WON,
                payout,
                f"Won: {direction} {line} (total: {total_score})",
            )
        else:
            direction = "Over" if is_over else "Under"
            return (
                BetStatus.LOST,
                0.0,
                f"Lost: {direction} {line} (total: {total_score})",
            )

    def _evaluate_parlay(self, bet: SimpleUnifiedBet) -> Tuple[BetStatus, float, str]:
        """
        Evaluate parlay bet based on leg statuses

        Rules:
        - If ANY leg is lost, entire parlay loses
        - If all legs are won (ignoring pushed legs), parlay wins
        - If all legs are pushed, parlay pushes
        - If any legs are still pending, parlay remains pending
        """
        db = SessionLocal()
        try:
            # Get all legs for this parlay
            legs = (
                db.query(SimpleUnifiedBet)
                .filter(SimpleUnifiedBet.parent_bet_id == bet.id)
                .all()
            )

            # Fallback: try parlay_legs JSON field if no legs found via parent_bet_id
            if not legs and hasattr(bet, "parlay_legs") and bet.parlay_legs:
                leg_ids = bet.parlay_legs if isinstance(bet.parlay_legs, list) else []
                if leg_ids:
                    legs = (
                        db.query(SimpleUnifiedBet)
                        .filter(SimpleUnifiedBet.id.in_(leg_ids))
                        .all()
                    )
                    logger.info(
                        f"Parlay {bet.id}: Found {len(legs)} legs via parlay_legs JSON field"
                    )

            if not legs:
                logger.warning(f"Parlay {bet.id}: No legs found, keeping as pending")
                return BetStatus.PENDING, 0.0, "Parlay has no legs"

            # Count leg statuses
            won_legs = 0
            lost_legs = 0
            pushed_legs = 0
            pending_legs = 0

            for leg in legs:
                if leg.status == BetStatus.WON:
                    won_legs += 1
                elif leg.status == BetStatus.LOST:
                    lost_legs += 1
                elif leg.status == BetStatus.PUSHED:
                    pushed_legs += 1
                elif leg.status == BetStatus.PENDING:
                    pending_legs += 1

            total_legs = len(legs)
            active_legs = total_legs - pushed_legs  # Pushes don't count

            logger.info(
                f"Parlay {bet.id}: {won_legs} won, {lost_legs} lost, "
                f"{pushed_legs} pushed, {pending_legs} pending out of {total_legs} total legs"
            )

            # RULE 1: If ANY leg lost, parlay loses
            if lost_legs > 0:
                return (
                    BetStatus.LOST,
                    0.0,
                    f"Parlay lost: {lost_legs} of {total_legs} legs lost",
                )

            # RULE 2: If any legs still pending, keep parlay pending
            if pending_legs > 0:
                return (
                    BetStatus.PENDING,
                    0.0,
                    f"Parlay pending: {pending_legs} legs still pending",
                )

            # RULE 3: All legs pushed - refund
            if active_legs == 0:
                return (
                    BetStatus.PUSHED,
                    bet.amount,
                    f"Parlay pushed: All {total_legs} legs pushed",
                )

            # RULE 4: All active legs won - parlay wins
            if won_legs == active_legs:
                payout = bet.amount + bet.potential_win
                return (
                    BetStatus.WON,
                    payout,
                    f"Parlay won: All {active_legs} active legs won",
                )

            # Shouldn't reach here, but safety fallback
            return BetStatus.PENDING, 0.0, "Unexpected parlay state"

        except Exception as e:
            logger.error(f"Error evaluating parlay {bet.id}: {e}")
            return BetStatus.PENDING, 0.0, f"Error evaluating parlay: {str(e)}"
        finally:
            db.close()

    async def _apply_results(self, results: List[UnifiedBetResult], db: Session):
        """Apply verification results to database"""

        for result in results:
            try:
                bet = (
                    db.query(SimpleUnifiedBet)
                    .filter(SimpleUnifiedBet.id == result.bet_id)
                    .first()
                )

                if bet and bet.status == BetStatus.PENDING:
                    bet.status = result.status
                    bet.result_amount = result.result_amount

                    if result.status != BetStatus.PENDING:
                        bet.settled_at = datetime.now(timezone.utc)

                    logger.info(
                        f"✅ Updated bet {result.bet_id[:8]}: {result.status.value} - {result.reasoning}"
                    )

            except Exception as e:
                logger.error(f"Error updating bet {result.bet_id[:8]}: {e}")

    def _normalize_sport(self, sport: str) -> str:
        """Normalize sport names for Odds API"""
        sport_mapping = {
            "mlb": "baseball_mlb",
            "nfl": "americanfootball_nfl",
            "nba": "basketball_nba",
            "nhl": "icehockey_nhl",
            "baseball": "baseball_mlb",
            "football": "americanfootball_nfl",
            "basketball": "basketball_nba",
            "hockey": "icehockey_nhl",
            "americanfootball_nfl": "americanfootball_nfl",
            "baseball_mlb": "baseball_mlb",
        }

        normalized = sport_mapping.get(sport.lower(), sport.lower())
        logger.debug(f"Normalized sport '{sport}' -> '{normalized}'")
        return normalized


# Create singleton instance
unified_bet_verification_service = UnifiedBetVerificationService()
