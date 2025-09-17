"""
Bet Verification Service - Automatically check and settle bet outcomes

This service:
1. Fetches completed game results from The Odds API
2. Determines bet outcomes (won/lost/pushed)
3. Updates bet statuses in the database
4. Calculates and assigns result amounts
5. Sends notifications to users
6. Handles both individual bets and parlays
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from app.core.database import SessionLocal
from app.models.database_models import (
    Bet,
    ParlayBet,
    Game,
    BetHistory,
    BetStatus,
    BetType,
    GameStatus,
)
from app.services.odds_api_service import OddsAPIService, Score
from app.services.websocket_manager import manager as websocket_manager
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class BetResult:
    """Result of evaluating a single bet"""

    bet_id: str
    status: BetStatus
    result_amount: float
    reasoning: str


@dataclass
class GameResult:
    """Processed game result for bet evaluation"""

    game_id: str
    sport: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    winner: Optional[str]  # "home", "away", or None for tie
    is_final: bool
    total_score: int


class BetVerificationService:
    """Service for automatically verifying and settling bets based on game results"""

    def __init__(self):
        self.odds_api_service = None

    async def __aenter__(self):
        """Async context manager entry"""
        self.odds_api_service = OddsAPIService(settings.ODDS_API_KEY)
        await self.odds_api_service.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.odds_api_service:
            await self.odds_api_service.__aexit__(exc_type, exc_val, exc_tb)

    async def verify_all_pending_bets(self) -> Dict:
        """
        Main method to verify all pending bets against completed games

        Returns:
            Dictionary with verification results and statistics
        """
        logger.info("Starting bet verification process")

        try:
            # Get all pending bets
            pending_bets = await self._get_pending_bets()
            pending_parlays = await self._get_pending_parlays()

            if not pending_bets and not pending_parlays:
                logger.info("No pending bets to verify")
                return {
                    "success": True,
                    "message": "No pending bets",
                    "verified": 0,
                    "settled": 0,
                }

            logger.info(
                f"Found {len(pending_bets)} pending bets and {len(pending_parlays)} pending parlays"
            )

            # Get unique game IDs from pending bets
            game_ids = set()
            for bet in pending_bets:
                if bet.game_id:
                    game_ids.add(bet.game_id)

            for parlay in pending_parlays:
                for leg in parlay.legs:
                    if leg.game_id:
                        game_ids.add(leg.game_id)

            if not game_ids:
                logger.info("No games to check for pending bets")
                return {
                    "success": True,
                    "message": "No games to verify",
                    "verified": 0,
                    "settled": 0,
                }

            # Get game results for all relevant games
            game_results = await self._get_game_results(list(game_ids))

            if not game_results:
                logger.info("No completed games found")
                return {
                    "success": True,
                    "message": "No completed games",
                    "verified": 0,
                    "settled": 0,
                }

            # Verify individual bets
            verified_bets = 0
            settled_bets = 0

            for bet in pending_bets:
                if bet.game_id in game_results:
                    try:
                        result = await self._verify_single_bet(
                            bet, game_results[bet.game_id]
                        )
                        if result:
                            await self._settle_bet(bet, result)
                            verified_bets += 1
                            if result.status in [
                                BetStatus.WON,
                                BetStatus.LOST,
                                BetStatus.PUSHED,
                            ]:
                                settled_bets += 1
                    except Exception as e:
                        logger.error(f"Error verifying bet {bet.id}: {e}")

            # Verify parlays
            for parlay in pending_parlays:
                try:
                    parlay_result = await self._verify_parlay(parlay, game_results)
                    if parlay_result:
                        await self._settle_parlay(parlay, parlay_result)
                        verified_bets += 1
                        if parlay_result.status in [
                            BetStatus.WON,
                            BetStatus.LOST,
                            BetStatus.PUSHED,
                        ]:
                            settled_bets += 1
                except Exception as e:
                    logger.error(f"Error verifying parlay {parlay.id}: {e}")

            logger.info(
                f"Verification complete: {verified_bets} bets verified, {settled_bets} settled"
            )

            return {
                "success": True,
                "message": f"Verified {verified_bets} bets, settled {settled_bets}",
                "verified": verified_bets,
                "settled": settled_bets,
                "games_checked": len(game_results),
            }

        except Exception as e:
            logger.error(f"Error in bet verification process: {e}")
            return {"success": False, "error": str(e)}

    async def _get_pending_bets(self) -> List[Bet]:
        """Get all individual pending bets (not parlay legs)"""
        db = SessionLocal()
        try:
            bets = (
                db.query(Bet)
                .filter(
                    and_(
                        Bet.status == BetStatus.PENDING,
                        Bet.parlay_id.is_(None),  # Only individual bets
                    )
                )
                .all()
            )
            return bets
        finally:
            db.close()

    async def _get_pending_parlays(self) -> List[ParlayBet]:
        """Get all pending parlay bets with their legs"""
        db = SessionLocal()
        try:
            parlays = (
                db.query(ParlayBet).filter(ParlayBet.status == BetStatus.PENDING).all()
            )

            # Attach legs to each parlay
            for parlay in parlays:
                parlay.legs = db.query(Bet).filter(Bet.parlay_id == parlay.id).all()

            return parlays
        finally:
            db.close()

    async def _get_game_results(self, game_ids: List[str]) -> Dict[str, GameResult]:
        """
        Fetch game results for specified game IDs from local database and The Odds API

        Returns:
            Dictionary mapping game_id to GameResult
        """
        game_results = {}

        # First, check for completed games in our local database
        db = SessionLocal()
        remaining_game_ids = []

        try:
            for game_id in game_ids:
                game = db.query(Game).filter(Game.id == game_id).first()
                if (
                    game
                    and game.status.upper() in ["FINAL", "COMPLETED"]
                    and game.home_score is not None
                    and game.away_score is not None
                ):
                    # We have a completed game in our database
                    game_result = GameResult(
                        game_id=game.id,
                        sport=game.sport_key or "unknown",
                        home_team=game.home_team,
                        away_team=game.away_team,
                        home_score=game.home_score,
                        away_score=game.away_score,
                        winner=self._determine_winner(game.home_score, game.away_score),
                        is_final=True,
                        total_score=game.home_score + game.away_score,
                    )
                    game_results[game.id] = game_result
                    logger.info(
                        f"Found completed game in database: {game.away_team} @ {game.home_team} - {game.away_score}-{game.home_score}"
                    )
                else:
                    # Need to check API for this game
                    remaining_game_ids.append(game_id)
        finally:
            db.close()

        # If all games were found locally, return early
        if not remaining_game_ids:
            return game_results

        logger.info(
            f"Found {len(game_results)} games locally, checking API for {len(remaining_game_ids)} remaining games"
        )

        # Group remaining games by sport for efficient API calls
        games_by_sport = {}

        db = SessionLocal()
        try:
            for game_id in remaining_game_ids:
                # Try to get sport from database first
                game = db.query(Game).filter(Game.id == game_id).first()
                if game and game.sport_key:
                    sport = game.sport_key
                else:
                    # Try to infer sport from game ID pattern
                    sport = self._infer_sport_from_game_id(game_id)

                if sport not in games_by_sport:
                    games_by_sport[sport] = []
                games_by_sport[sport].append(game_id)
        finally:
            db.close()

        # Fetch scores for each sport from API
        for sport, sport_game_ids in games_by_sport.items():
            try:
                logger.info(f"Fetching scores for {sport}: {sport_game_ids}")
                scores = await self.odds_api_service.get_scores(sport, days_from=3)

                for score in scores:
                    if score.id in sport_game_ids and score.completed:
                        game_result = GameResult(
                            game_id=score.id,
                            sport=score.sport_key,
                            home_team=score.home_team,
                            away_team=score.away_team,
                            home_score=score.home_score or 0,
                            away_score=score.away_score or 0,
                            winner=self._determine_winner(
                                score.home_score, score.away_score
                            ),
                            is_final=score.completed,
                            total_score=(score.home_score or 0)
                            + (score.away_score or 0),
                        )
                        game_results[score.id] = game_result
                        logger.info(
                            f"Game result: {score.away_team} @ {score.home_team} - {score.away_score}-{score.home_score}"
                        )

            except Exception as e:
                logger.error(f"Error fetching scores for sport {sport}: {e}")
                continue

        return game_results

    def _infer_sport_from_game_id(self, game_id: str) -> str:
        """Infer sport from game ID pattern"""
        if game_id.startswith("nfl-"):
            return "americanfootball_nfl"
        elif game_id.startswith("mlb-"):
            return "baseball_mlb"
        elif game_id.startswith("nba-"):
            return "basketball_nba"
        elif game_id.startswith("nhl-"):
            return "icehockey_nhl"
        elif game_id.startswith("ncaaf-"):
            return "americanfootball_ncaaf"
        elif game_id.startswith("ncaab-"):
            return "basketball_ncaab"
        else:
            return "americanfootball_nfl"  # Default fallback

    def _determine_winner(
        self, home_score: Optional[int], away_score: Optional[int]
    ) -> Optional[str]:
        """Determine game winner"""
        if home_score is None or away_score is None:
            return None

        if home_score > away_score:
            return "home"
        elif away_score > home_score:
            return "away"
        else:
            return None  # Tie

    async def _verify_single_bet(
        self, bet: Bet, game_result: GameResult
    ) -> Optional[BetResult]:
        """
        Verify a single bet against game result

        Returns:
            BetResult with outcome or None if bet cannot be verified
        """
        if not game_result.is_final:
            return None

        try:
            if bet.bet_type == BetType.MONEYLINE:
                return self._verify_moneyline_bet(bet, game_result)
            elif bet.bet_type == BetType.SPREAD:
                return self._verify_spread_bet(bet, game_result)
            elif bet.bet_type == BetType.TOTAL:
                return self._verify_total_bet(bet, game_result)
            else:
                logger.warning(f"Unsupported bet type: {bet.bet_type}")
                return None

        except Exception as e:
            logger.error(f"Error verifying bet {bet.id}: {e}")
            return None

    def _verify_moneyline_bet(self, bet: Bet, game_result: GameResult) -> BetResult:
        """Verify moneyline bet"""
        selection_lower = bet.selection.lower()

        # Determine if bet was on home or away team
        is_home_bet = (
            game_result.home_team.lower() in selection_lower
            or selection_lower in game_result.home_team.lower()
        )
        is_away_bet = (
            game_result.away_team.lower() in selection_lower
            or selection_lower in game_result.away_team.lower()
        )

        if game_result.winner is None:  # Tie
            # Most sportsbooks push moneyline bets on ties (except soccer/hockey with 3-way lines)
            return BetResult(
                bet_id=bet.id,
                status=BetStatus.PUSHED,
                result_amount=bet.amount,  # Return original bet amount
                reasoning=f"Game ended in tie: {game_result.away_team} {game_result.away_score} - {game_result.home_team} {game_result.home_score}",
            )

        won = False
        if is_home_bet and game_result.winner == "home":
            won = True
        elif is_away_bet and game_result.winner == "away":
            won = True

        if won:
            result_amount = bet.amount + bet.potential_win
            return BetResult(
                bet_id=bet.id,
                status=BetStatus.WON,
                result_amount=result_amount,
                reasoning=f"Moneyline bet won: {bet.selection} - Final: {game_result.away_team} {game_result.away_score} - {game_result.home_team} {game_result.home_score}",
            )
        else:
            return BetResult(
                bet_id=bet.id,
                status=BetStatus.LOST,
                result_amount=0,
                reasoning=f"Moneyline bet lost: {bet.selection} - Final: {game_result.away_team} {game_result.away_score} - {game_result.home_team} {game_result.home_score}",
            )

    def _verify_spread_bet(self, bet: Bet, game_result: GameResult) -> BetResult:
        """Verify point spread bet"""
        try:
            # Parse spread from selection (e.g., "Chiefs -3.5" or "Cowboys +7")
            spread_value = self._extract_spread_from_selection(bet.selection)
            if spread_value is None:
                raise ValueError(f"Cannot parse spread from selection: {bet.selection}")

            selection_lower = bet.selection.lower()
            is_home_bet = (
                game_result.home_team.lower() in selection_lower
                or selection_lower in game_result.home_team.lower()
            )

            # Calculate adjusted scores
            if is_home_bet:
                adjusted_home_score = game_result.home_score + spread_value
                won = adjusted_home_score > game_result.away_score
                pushed = adjusted_home_score == game_result.away_score
            else:
                adjusted_away_score = game_result.away_score + spread_value
                won = adjusted_away_score > game_result.home_score
                pushed = adjusted_away_score == game_result.home_score

            if pushed:
                return BetResult(
                    bet_id=bet.id,
                    status=BetStatus.PUSHED,
                    result_amount=bet.amount,
                    reasoning=f"Spread bet pushed: {bet.selection} - Final: {game_result.away_team} {game_result.away_score} - {game_result.home_team} {game_result.home_score}",
                )
            elif won:
                result_amount = bet.amount + bet.potential_win
                return BetResult(
                    bet_id=bet.id,
                    status=BetStatus.WON,
                    result_amount=result_amount,
                    reasoning=f"Spread bet won: {bet.selection} - Final: {game_result.away_team} {game_result.away_score} - {game_result.home_team} {game_result.home_score}",
                )
            else:
                return BetResult(
                    bet_id=bet.id,
                    status=BetStatus.LOST,
                    result_amount=0,
                    reasoning=f"Spread bet lost: {bet.selection} - Final: {game_result.away_team} {game_result.away_score} - {game_result.home_team} {game_result.home_score}",
                )

        except Exception as e:
            logger.error(f"Error verifying spread bet {bet.id}: {e}")
            return BetResult(
                bet_id=bet.id,
                status=BetStatus.CANCELLED,
                result_amount=bet.amount,
                reasoning=f"Error processing spread bet: {str(e)}",
            )

    def _verify_total_bet(self, bet: Bet, game_result: GameResult) -> BetResult:
        """Verify over/under total bet"""
        try:
            # Parse total from selection (e.g., "Over 45.5" or "Under 228.5")
            total_value = self._extract_total_from_selection(bet.selection)
            if total_value is None:
                raise ValueError(f"Cannot parse total from selection: {bet.selection}")

            is_over = "over" in bet.selection.lower()

            if game_result.total_score == total_value:
                # Push
                return BetResult(
                    bet_id=bet.id,
                    status=BetStatus.PUSHED,
                    result_amount=bet.amount,
                    reasoning=f"Total bet pushed: {bet.selection} - Total score: {game_result.total_score}",
                )

            won = False
            if is_over and game_result.total_score > total_value:
                won = True
            elif not is_over and game_result.total_score < total_value:
                won = True

            if won:
                result_amount = bet.amount + bet.potential_win
                return BetResult(
                    bet_id=bet.id,
                    status=BetStatus.WON,
                    result_amount=result_amount,
                    reasoning=f"Total bet won: {bet.selection} - Total score: {game_result.total_score}",
                )
            else:
                return BetResult(
                    bet_id=bet.id,
                    status=BetStatus.LOST,
                    result_amount=0,
                    reasoning=f"Total bet lost: {bet.selection} - Total score: {game_result.total_score}",
                )

        except Exception as e:
            logger.error(f"Error verifying total bet {bet.id}: {e}")
            return BetResult(
                bet_id=bet.id,
                status=BetStatus.CANCELLED,
                result_amount=bet.amount,
                reasoning=f"Error processing total bet: {str(e)}",
            )

    def _extract_spread_from_selection(self, selection: str) -> Optional[float]:
        """Extract spread value from bet selection"""
        import re

        # Look for patterns like "-3.5", "+7", "-14", "+10.5"
        match = re.search(r"([+-]?\d+\.?\d*)", selection)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def _extract_total_from_selection(self, selection: str) -> Optional[float]:
        """Extract total value from bet selection"""
        import re

        # Look for patterns like "Over 45.5", "Under 228.5"
        match = re.search(r"(\d+\.?\d*)", selection)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    async def _verify_parlay(
        self, parlay: ParlayBet, game_results: Dict[str, GameResult]
    ) -> Optional[BetResult]:
        """
        Verify a parlay bet (all legs must win)

        Returns:
            BetResult for the entire parlay, and settles individual legs
        """
        if not hasattr(parlay, "legs") or not parlay.legs:
            return None

        leg_results = []
        pending_legs = 0
        won_legs = 0
        lost_legs = 0
        pushed_legs = 0

        for leg in parlay.legs:
            if leg.game_id not in game_results:
                pending_legs += 1
                continue

            game_result = game_results[leg.game_id]
            if not game_result.is_final:
                pending_legs += 1
                continue

            leg_result = await self._verify_single_bet(leg, game_result)
            if not leg_result:
                pending_legs += 1
                continue

            leg_results.append(leg_result)

            # Settle individual leg with its actual outcome
            await self._settle_bet(leg, leg_result)

            if leg_result.status == BetStatus.WON:
                won_legs += 1
            elif leg_result.status == BetStatus.LOST:
                lost_legs += 1
            elif leg_result.status == BetStatus.PUSHED:
                pushed_legs += 1

        # If any legs are still pending, don't settle the parlay yet
        if pending_legs > 0:
            return None

        total_legs = len(parlay.legs)
        active_legs = (
            total_legs - pushed_legs
        )  # Pushes reduce the number of legs needed

        # Parlay rules:
        # - If any leg loses, entire parlay loses
        # - If all remaining legs (after pushes) win, parlay wins
        # - If all legs push, parlay pushes

        if lost_legs > 0:
            # Parlay lost
            return BetResult(
                bet_id=parlay.id,
                status=BetStatus.LOST,
                result_amount=0,
                reasoning=f"Parlay lost: {lost_legs} of {total_legs} legs lost",
            )
        elif active_legs == 0:
            # All legs pushed
            return BetResult(
                bet_id=parlay.id,
                status=BetStatus.PUSHED,
                result_amount=parlay.amount,
                reasoning=f"Parlay pushed: All {total_legs} legs pushed",
            )
        elif won_legs == active_legs:
            # All active legs won
            # Recalculate payout based on reduced legs (pushes removed)
            adjusted_payout = self._calculate_adjusted_parlay_payout(
                parlay, leg_results
            )
            return BetResult(
                bet_id=parlay.id,
                status=BetStatus.WON,
                result_amount=parlay.amount + adjusted_payout,
                reasoning=f"Parlay won: {won_legs} legs won, {pushed_legs} legs pushed",
            )
        else:
            # This shouldn't happen if logic is correct
            logger.error(
                f"Unexpected parlay state: {won_legs} won, {lost_legs} lost, {pushed_legs} pushed, {pending_legs} pending"
            )
            return None

    def _calculate_adjusted_parlay_payout(
        self, parlay: ParlayBet, leg_results: List[BetResult]
    ) -> float:
        """Calculate adjusted payout for parlay with pushed legs removed"""
        winning_legs = [
            result for result in leg_results if result.status == BetStatus.WON
        ]

        if len(winning_legs) <= 1:
            # With pushes, might end up with 1 or 0 legs - treat as original single bet odds
            return parlay.potential_win

        # Recalculate based on remaining legs (simplified - would need actual leg odds for precise calculation)
        # For now, use the original potential win adjusted proportionally
        adjustment_factor = len(winning_legs) / parlay.leg_count
        return parlay.potential_win * adjustment_factor

    async def _settle_bet(self, bet: Bet, result: BetResult) -> None:
        """Update database with bet result"""
        db = SessionLocal()
        try:
            # Update bet status
            db_bet = db.query(Bet).filter(Bet.id == bet.id).first()
            if not db_bet:
                logger.error(f"Bet {bet.id} not found for settlement")
                return

            old_status = db_bet.status
            db_bet.status = result.status
            db_bet.result_amount = result.result_amount
            db_bet.settled_at = datetime.utcnow()

            # Log bet history
            history = BetHistory(
                user_id=db_bet.user_id,
                bet_id=db_bet.id,
                action="settled",
                old_status=old_status.value,
                new_status=result.status.value,
                amount=result.result_amount,
                bet_metadata={"reasoning": result.reasoning},
            )
            db.add(history)

            db.commit()

            # Send real-time notification
            await self._send_bet_notification(db_bet, result)

            logger.info(
                f"Settled bet {bet.id}: {result.status.value} - ${result.result_amount}"
            )

        except Exception as e:
            db.rollback()
            logger.error(f"Error settling bet {bet.id}: {e}")
        finally:
            db.close()

    async def _settle_parlay(self, parlay: ParlayBet, result: BetResult) -> None:
        """Update database with parlay result and individual leg outcomes"""
        db = SessionLocal()
        try:
            # Update parlay status
            db_parlay = db.query(ParlayBet).filter(ParlayBet.id == parlay.id).first()
            if not db_parlay:
                logger.error(f"Parlay {parlay.id} not found for settlement")
                return

            old_status = db_parlay.status
            db_parlay.status = result.status
            db_parlay.result_amount = result.result_amount
            db_parlay.settled_at = datetime.utcnow()

            # Don't automatically update leg statuses - they should be settled individually
            # based on their actual game outcomes, not the parlay result

            # Log parlay history
            history = BetHistory(
                user_id=db_parlay.user_id,
                bet_id=db_parlay.id,
                action="settled",
                old_status=old_status.value,
                new_status=result.status.value,
                amount=result.result_amount,
                bet_metadata={"reasoning": result.reasoning, "type": "parlay"},
            )
            db.add(history)

            db.commit()

            # Send real-time notification
            await self._send_parlay_notification(db_parlay, result)

            logger.info(
                f"Settled parlay {parlay.id}: {result.status.value} - ${result.result_amount}"
            )

        except Exception as e:
            db.rollback()
            logger.error(f"Error settling parlay {parlay.id}: {e}")
        finally:
            db.close()

    async def _send_bet_notification(self, bet: Bet, result: BetResult) -> None:
        """Send real-time notification for bet result"""
        try:
            if result.status == BetStatus.WON:
                notification_type = "bet_won"
                title = "🎉 Bet Won!"
                message = f"Your ${bet.amount} bet on {bet.selection} won ${result.result_amount - bet.amount:.2f}!"
            elif result.status == BetStatus.LOST:
                notification_type = "bet_lost"
                title = "😞 Bet Lost"
                message = f"Your ${bet.amount} bet on {bet.selection} did not win."
            elif result.status == BetStatus.PUSHED:
                notification_type = "bet_pushed"
                title = "↔️ Bet Pushed"
                message = f"Your ${bet.amount} bet on {bet.selection} was pushed. Your stake has been returned."
            else:
                return  # Don't send notifications for cancelled bets

            await websocket_manager.send_notification(
                user_id=bet.user_id,
                notification={
                    "type": notification_type,
                    "title": title,
                    "message": message,
                    "priority": "high",
                    "data": {
                        "bet_id": bet.id,
                        "amount": bet.amount,
                        "result_amount": result.result_amount,
                        "status": result.status.value,
                        "reasoning": result.reasoning,
                    },
                },
            )
        except Exception as e:
            logger.error(f"Error sending notification for bet {bet.id}: {e}")

    async def _send_parlay_notification(
        self, parlay: ParlayBet, result: BetResult
    ) -> None:
        """Send real-time notification for parlay result"""
        try:
            if result.status == BetStatus.WON:
                notification_type = "bet_won"
                title = "🎉 Parlay Won!"
                message = f"Your ${parlay.amount} {parlay.leg_count}-leg parlay won ${result.result_amount - parlay.amount:.2f}!"
            elif result.status == BetStatus.LOST:
                notification_type = "bet_lost"
                title = "😞 Parlay Lost"
                message = (
                    f"Your ${parlay.amount} {parlay.leg_count}-leg parlay did not win."
                )
            elif result.status == BetStatus.PUSHED:
                notification_type = "bet_pushed"
                title = "↔️ Parlay Pushed"
                message = f"Your ${parlay.amount} {parlay.leg_count}-leg parlay was pushed. Your stake has been returned."
            else:
                return  # Don't send notifications for cancelled parlays

            await websocket_manager.send_notification(
                user_id=parlay.user_id,
                notification={
                    "type": notification_type,
                    "title": title,
                    "message": message,
                    "priority": "high",
                    "data": {
                        "parlay_id": parlay.id,
                        "amount": parlay.amount,
                        "result_amount": result.result_amount,
                        "status": result.status.value,
                        "leg_count": parlay.leg_count,
                        "reasoning": result.reasoning,
                    },
                },
            )
        except Exception as e:
            logger.error(f"Error sending notification for parlay {parlay.id}: {e}")


# Initialize service
bet_verification_service = BetVerificationService()
