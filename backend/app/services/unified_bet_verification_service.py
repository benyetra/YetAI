"""
Unified Bet Verification Service - Modern verification for unified betting system

This service works with the SimpleUnifiedBet model and uses The Odds API for verification:
1. Fetches pending bets from simple_unified_bets table
2. Uses odds_api_event_id to get game results from The Odds API
3. Determines bet outcomes based on real API data
4. Updates bet statuses and calculates payouts
5. Handles individual bets, parlays, and live bets uniformly
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
from app.models.simple_unified_bet_model import SimpleUnifiedBet
from app.models.database_models import BetStatus, BetType, TeamSide, OverUnder
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
        self.odds_service = get_optimized_odds_service()

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
                logger.info(f"Bet {bet.id[:8]}: status={bet.status} ({type(bet.status)}) - {bet.selection}")

            # Get all pending bets from unified table
            pending_bets = db.query(SimpleUnifiedBet).filter(
                SimpleUnifiedBet.status == BetStatus.PENDING
            ).all()

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
                    logger.warning(f"Skipping {len(sport_bets)} bets with unknown sport")
                    continue

                try:
                    logger.info(f"Verifying {len(sport_bets)} {sport.upper()} bets...")

                    # Get completed games for this sport (last 3 days)
                    normalized_sport = self._normalize_sport(sport)
                    completed_games = await self.odds_service.get_scores_optimized(
                        normalized_sport, include_completed=True
                    )

                    logger.info(f"Retrieved {len(completed_games)} game results for {sport}")

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
            logger.info(f"✅ Unified verification complete: {total_settled} settled, {total_verified} verified in {duration:.1f}s")

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
            logger.debug(f"Game {bet.odds_api_event_id[:8]} not found in completed games")
            return None

        # Check if game is completed
        if not game_data.get("completed", False):
            logger.debug(f"Game {bet.odds_api_event_id[:8]} not yet completed")
            return None

        # Get final scores
        scores = game_data.get("scores")
        if not scores or len(scores) < 2:
            logger.warning(f"Invalid scores for game {bet.odds_api_event_id[:8]}")
            return None

        home_score = scores[0].get("score", 0)
        away_score = scores[1].get("score", 0)

        logger.info(f"Verifying bet {bet.id[:8]}: {bet.bet_type.value} - {bet.selection}")
        logger.info(f"Final score: {bet.away_team} {away_score} - {bet.home_team} {home_score}")

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
            reasoning=reasoning
        )

    def _evaluate_moneyline(
        self, bet: SimpleUnifiedBet, home_score: int, away_score: int
    ) -> Tuple[BetStatus, float, str]:
        """Evaluate moneyline bet"""

        if home_score == away_score:
            return BetStatus.PUSHED, bet.amount, "Game tied - bet pushed"

        winner = "home" if home_score > away_score else "away"

        # Parse selection - could be "home", "away", or team name
        selection = bet.selection.lower()
        bet_winner = None

        if selection in ["home", winner] or (bet.selected_team_name and bet.selected_team_name.lower() == bet.home_team.lower() and winner == "home"):
            bet_winner = "home"
        elif selection in ["away"] or (bet.selected_team_name and bet.selected_team_name.lower() == bet.away_team.lower() and winner == "away"):
            bet_winner = "away"
        elif bet.selected_team_name:
            # Team name selection
            if bet.selected_team_name.lower() == bet.home_team.lower():
                bet_winner = "home"
            elif bet.selected_team_name.lower() == bet.away_team.lower():
                bet_winner = "away"

        if bet_winner == winner:
            payout = bet.amount + bet.potential_win
            return BetStatus.WON, payout, f"Won: {bet.selected_team_name or selection} won"
        else:
            return BetStatus.LOST, 0.0, f"Lost: {bet.selected_team_name or selection} lost"

    def _evaluate_spread(
        self, bet: SimpleUnifiedBet, home_score: int, away_score: int
    ) -> Tuple[BetStatus, float, str]:
        """Evaluate spread bet"""

        if not bet.spread_value:
            return BetStatus.LOST, 0.0, "Invalid spread value"

        spread = bet.spread_value

        # Apply spread to selected team
        if bet.spread_selection == TeamSide.HOME:
            adjusted_home = home_score + spread
            if adjusted_home > away_score:
                payout = bet.amount + bet.potential_win
                return BetStatus.WON, payout, f"Won: Home +{spread} covered"
            elif adjusted_home == away_score:
                return BetStatus.PUSHED, bet.amount, f"Push: Home +{spread} tied"
            else:
                return BetStatus.LOST, 0.0, f"Lost: Home +{spread} didn't cover"
        else:  # AWAY
            adjusted_away = away_score + spread
            if adjusted_away > home_score:
                payout = bet.amount + bet.potential_win
                return BetStatus.WON, payout, f"Won: Away +{spread} covered"
            elif adjusted_away == home_score:
                return BetStatus.PUSHED, bet.amount, f"Push: Away +{spread} tied"
            else:
                return BetStatus.LOST, 0.0, f"Lost: Away +{spread} didn't cover"

    def _evaluate_total(
        self, bet: SimpleUnifiedBet, home_score: int, away_score: int
    ) -> Tuple[BetStatus, float, str]:
        """Evaluate total (over/under) bet"""

        if not bet.total_points:
            return BetStatus.LOST, 0.0, "Invalid total points value"

        total_score = home_score + away_score
        line = bet.total_points

        # Determine if bet was over or under
        selection = bet.selection.lower()
        is_over = "over" in selection or bet.over_under_selection == OverUnder.OVER

        if total_score == line:
            return BetStatus.PUSHED, bet.amount, f"Push: Total exactly {line}"
        elif (is_over and total_score > line) or (not is_over and total_score < line):
            payout = bet.amount + bet.potential_win
            direction = "Over" if is_over else "Under"
            return BetStatus.WON, payout, f"Won: {direction} {line} (total: {total_score})"
        else:
            direction = "Over" if is_over else "Under"
            return BetStatus.LOST, 0.0, f"Lost: {direction} {line} (total: {total_score})"

    def _evaluate_parlay(self, bet: SimpleUnifiedBet) -> Tuple[BetStatus, float, str]:
        """Evaluate parlay bet - check all legs"""
        # For now, return pending - parlay evaluation is complex
        # Would need to check all legs in the parlay
        return BetStatus.PENDING, 0.0, "Parlay evaluation not yet implemented"

    async def _apply_results(self, results: List[UnifiedBetResult], db: Session):
        """Apply verification results to database"""

        for result in results:
            try:
                bet = db.query(SimpleUnifiedBet).filter(
                    SimpleUnifiedBet.id == result.bet_id
                ).first()

                if bet and bet.status == BetStatus.PENDING:
                    bet.status = result.status
                    bet.result_amount = result.result_amount

                    if result.status != BetStatus.PENDING:
                        bet.settled_at = datetime.now(timezone.utc)

                    logger.info(f"✅ Updated bet {result.bet_id[:8]}: {result.status.value} - {result.reasoning}")

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