"""
Simple Unified Bet Service - Single service for all betting operations

This service replaces the separate bet, parlay, live, and yetai bet services
by using the unified simple_unified_bets table structure.
"""

import uuid
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
from app.core.database import get_db, SessionLocal
from app.models.database_models import User, Game, BetHistory, BetLimit
from app.models.simple_unified_bet_model import (
    SimpleUnifiedBet,
    BetStatus,
    BetType,
    BetSource,
    TeamSide,
    OverUnder,
    GameStatus,
    SubscriptionTier,
)
from app.models.bet_models import PlaceBetRequest, PlaceParlayRequest
from app.models.live_bet_models import PlaceLiveBetRequest

logger = logging.getLogger(__name__)


class SimpleUnifiedBetService:
    """Unified bet service for all betting operations"""

    def __init__(self):
        self.bet_limits = {"daily": 5000, "weekly": 20000, "single_bet": 10000}

    async def place_bet(self, user_id: int, bet_data: PlaceBetRequest) -> Dict:
        """Place a single straight bet"""
        try:
            db = SessionLocal()
            try:
                # Validate bet limits
                if not await self._check_bet_limits(user_id, bet_data.amount, db):
                    return {"success": False, "error": "Bet exceeds limits"}

                # Get or create game record
                game = await self._get_or_create_game(bet_data, db)

                # Generate bet ID
                bet_id = str(uuid.uuid4())

                # Calculate potential win from odds and amount
                potential_win = self._calculate_potential_win(
                    bet_data.odds, bet_data.amount
                )

                # Parse bet selection for structured data
                bet_type_str = (
                    bet_data.bet_type.value
                    if hasattr(bet_data.bet_type, "value")
                    else str(bet_data.bet_type)
                )
                parsed_selection = self._parse_bet_selection(
                    bet_data.selection,
                    bet_type_str,
                    bet_data.home_team,
                    bet_data.away_team,
                )

                # Create unified bet record
                unified_bet = SimpleUnifiedBet(
                    id=bet_id,
                    user_id=user_id,
                    odds_api_event_id=game.id if game else bet_data.game_id,
                    game_id=game.id if game else bet_data.game_id,
                    bet_type=BetType(bet_type_str.lower()),
                    amount=bet_data.amount,
                    odds=bet_data.odds,
                    potential_win=potential_win,
                    selection=bet_data.selection,
                    home_team=bet_data.home_team,
                    away_team=bet_data.away_team,
                    sport=bet_data.sport,
                    commence_time=bet_data.commence_time,
                    source=BetSource.STRAIGHT,
                    bookmaker=getattr(bet_data, "bookmaker", "fanduel"),
                    line_value=getattr(bet_data, "line_value", None),
                    # Add structured data from parsing
                    team_selection=parsed_selection.get(
                        "team_selection", TeamSide.NONE
                    ),
                    selected_team_name=parsed_selection.get("selected_team_name"),
                    spread_value=parsed_selection.get("spread_value"),
                    spread_selection=parsed_selection.get(
                        "spread_selection", TeamSide.NONE
                    ),
                    total_points=parsed_selection.get("total_points"),
                    over_under_selection=parsed_selection.get(
                        "over_under_selection", OverUnder.NONE
                    ),
                )

                db.add(unified_bet)
                db.commit()

                logger.info(f"Placed bet {bet_id} for user {user_id}")

                return {
                    "success": True,
                    "bet_id": bet_id,
                    "message": f"Bet placed successfully",
                    "bet": self._format_bet_response(unified_bet),
                }

            except Exception as e:
                db.rollback()
                logger.error(f"Error placing bet: {e}")
                return {"success": False, "error": str(e)}
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error in place_bet: {e}")
            return {"success": False, "error": str(e)}

    async def place_parlay(self, user_id: int, parlay_data: PlaceParlayRequest) -> Dict:
        """Place a parlay bet with multiple legs"""
        try:
            db = SessionLocal()
            try:
                # Validate bet limits
                if not await self._check_bet_limits(
                    user_id, parlay_data.total_amount, db
                ):
                    return {"success": False, "error": "Parlay exceeds bet limits"}

                # Generate parlay parent ID
                parlay_id = str(uuid.uuid4())

                # Create parlay parent record
                parlay_parent = SimpleUnifiedBet(
                    id=parlay_id,
                    user_id=user_id,
                    odds_api_event_id=f"parlay_{parlay_id[:8]}",
                    bet_type=BetType.PARLAY,
                    amount=parlay_data.total_amount,
                    odds=parlay_data.total_odds,
                    potential_win=parlay_data.potential_win,
                    selection=f"Parlay ({len(parlay_data.legs)} legs)",
                    home_team="Multiple Teams",
                    away_team="Multiple Teams",
                    sport="Multiple Sports",
                    commence_time=datetime.utcnow(),
                    source=BetSource.PARLAYS,
                    bookmaker="fanduel",
                    is_parlay=True,
                    leg_count=len(parlay_data.legs),
                    total_odds=parlay_data.total_odds,
                    parlay_legs=json.dumps([leg.dict() for leg in parlay_data.legs]),
                )

                db.add(parlay_parent)

                # Create leg records
                leg_ids = []
                for i, leg in enumerate(parlay_data.legs):
                    leg_id = str(uuid.uuid4())
                    leg_ids.append(leg_id)

                    # Get game for this leg
                    game = await self._get_or_create_game(leg, db)

                    # Parse leg selection
                    leg_bet_type_str = (
                        leg.bet_type.value
                        if hasattr(leg.bet_type, "value")
                        else str(leg.bet_type)
                    )
                    parsed_selection = self._parse_bet_selection(
                        leg.selection, leg_bet_type_str, leg.home_team, leg.away_team
                    )

                    parlay_leg = SimpleUnifiedBet(
                        id=leg_id,
                        user_id=user_id,
                        odds_api_event_id=game.id if game else leg.game_id,
                        game_id=game.id if game else leg.game_id,
                        bet_type=BetType(leg_bet_type_str.lower()),
                        amount=0,  # Individual leg amounts not stored
                        odds=leg.odds,
                        potential_win=0,  # Calculated at parlay level
                        selection=leg.selection,
                        home_team=leg.home_team,
                        away_team=leg.away_team,
                        sport=leg.sport,
                        commence_time=leg.commence_time,
                        source=BetSource.PARLAYS,
                        bookmaker=leg.bookmaker,
                        parent_bet_id=parlay_id,  # Link to parent
                        is_parlay=False,  # This is a leg, not parent
                        leg_count=1,
                        leg_position=i + 1,
                        # Structured data
                        team_selection=parsed_selection.get(
                            "team_selection", TeamSide.NONE
                        ),
                        selected_team_name=parsed_selection.get("selected_team_name"),
                        spread_value=parsed_selection.get("spread_value"),
                        spread_selection=parsed_selection.get(
                            "spread_selection", TeamSide.NONE
                        ),
                        total_points=parsed_selection.get("total_points"),
                        over_under_selection=parsed_selection.get(
                            "over_under_selection", OverUnder.NONE
                        ),
                    )

                    db.add(parlay_leg)

                db.commit()

                logger.info(
                    f"Placed parlay {parlay_id} with {len(parlay_data.legs)} legs for user {user_id}"
                )

                return {
                    "success": True,
                    "parlay_id": parlay_id,
                    "leg_ids": leg_ids,
                    "message": f"Parlay with {len(parlay_data.legs)} legs placed successfully",
                    "parlay": self._format_bet_response(parlay_parent),
                }

            except Exception as e:
                db.rollback()
                logger.error(f"Error placing parlay: {e}")
                return {"success": False, "error": str(e)}
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error in place_parlay: {e}")
            return {"success": False, "error": str(e)}

    async def place_live_bet(
        self, user_id: int, live_bet_data: PlaceLiveBetRequest
    ) -> Dict:
        """Place a live bet during game play"""
        try:
            db = SessionLocal()
            try:
                # Validate bet limits
                if not await self._check_bet_limits(user_id, live_bet_data.amount, db):
                    return {"success": False, "error": "Live bet exceeds limits"}

                # Generate bet ID
                bet_id = str(uuid.uuid4())

                # Parse selection
                live_bet_type_str = (
                    live_bet_data.bet_type.value
                    if hasattr(live_bet_data.bet_type, "value")
                    else str(live_bet_data.bet_type)
                )
                parsed_selection = self._parse_bet_selection(
                    live_bet_data.selection,
                    live_bet_type_str,
                    live_bet_data.home_team,
                    live_bet_data.away_team,
                )

                # Create live bet record
                live_bet = SimpleUnifiedBet(
                    id=bet_id,
                    user_id=user_id,
                    odds_api_event_id=live_bet_data.game_id or f"live_{bet_id[:8]}",
                    game_id=live_bet_data.game_id,
                    bet_type=BetType(live_bet_type_str.lower()),
                    amount=live_bet_data.amount,
                    odds=live_bet_data.odds,
                    potential_win=live_bet_data.potential_win,
                    selection=live_bet_data.selection,
                    home_team=live_bet_data.home_team,
                    away_team=live_bet_data.away_team,
                    sport=getattr(live_bet_data, "sport", "Unknown"),
                    commence_time=getattr(
                        live_bet_data, "commence_time", datetime.utcnow()
                    ),
                    source=BetSource.LIVE,
                    bookmaker="fanduel",
                    is_live=True,
                    game_time_at_placement=getattr(live_bet_data, "game_time", None),
                    score_at_placement=getattr(live_bet_data, "current_score", None),
                    cash_out_available=getattr(
                        live_bet_data, "cash_out_available", False
                    ),
                    cash_out_value=getattr(live_bet_data, "cash_out_value", None),
                    # Structured data
                    team_selection=parsed_selection.get(
                        "team_selection", TeamSide.NONE
                    ),
                    selected_team_name=parsed_selection.get("selected_team_name"),
                    spread_value=parsed_selection.get("spread_value"),
                    spread_selection=parsed_selection.get(
                        "spread_selection", TeamSide.NONE
                    ),
                    total_points=parsed_selection.get("total_points"),
                    over_under_selection=parsed_selection.get(
                        "over_under_selection", OverUnder.NONE
                    ),
                )

                db.add(live_bet)
                db.commit()

                logger.info(f"Placed live bet {bet_id} for user {user_id}")

                return {
                    "success": True,
                    "bet_id": bet_id,
                    "message": "Live bet placed successfully",
                    "bet": self._format_bet_response(live_bet),
                }

            except Exception as e:
                db.rollback()
                logger.error(f"Error placing live bet: {e}")
                return {"success": False, "error": str(e)}
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error in place_live_bet: {e}")
            return {"success": False, "error": str(e)}

    async def get_user_bets(
        self, user_id: int, include_legs: bool = False
    ) -> List[Dict]:
        """Get all bets for a user"""
        try:
            db = SessionLocal()
            try:
                query = db.query(SimpleUnifiedBet).filter(
                    SimpleUnifiedBet.user_id == user_id
                )

                if not include_legs:
                    # Exclude parlay legs, only show parent parlays and straight bets
                    query = query.filter(SimpleUnifiedBet.parent_bet_id.is_(None))

                bets = query.order_by(desc(SimpleUnifiedBet.placed_at)).all()

                return [self._format_bet_response(bet) for bet in bets]

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error getting user bets: {e}")
            return []

    async def get_bet_by_id(self, bet_id: str) -> Optional[Dict]:
        """Get a specific bet by ID"""
        try:
            db = SessionLocal()
            try:
                bet = (
                    db.query(SimpleUnifiedBet)
                    .filter(SimpleUnifiedBet.id == bet_id)
                    .first()
                )

                if not bet:
                    return None

                bet_data = self._format_bet_response(bet)

                # If it's a parlay parent, include legs
                if bet.is_parlay:
                    legs = (
                        db.query(SimpleUnifiedBet)
                        .filter(SimpleUnifiedBet.parent_bet_id == bet_id)
                        .order_by(SimpleUnifiedBet.leg_position)
                        .all()
                    )

                    bet_data["legs"] = [self._format_bet_response(leg) for leg in legs]

                return bet_data

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error getting bet {bet_id}: {e}")
            return None

    async def get_user_stats(self, user_id: int) -> Dict:
        """Get betting statistics for a user"""
        try:
            db = SessionLocal()
            try:
                # Get all non-leg bets (straight bets and parlay parents)
                bets = (
                    db.query(SimpleUnifiedBet)
                    .filter(
                        and_(
                            SimpleUnifiedBet.user_id == user_id,
                            SimpleUnifiedBet.parent_bet_id.is_(None),
                        )
                    )
                    .all()
                )

                total_bets = len(bets)
                total_wagered = sum(bet.amount for bet in bets)
                total_won = sum(
                    bet.result_amount or 0
                    for bet in bets
                    if bet.status == BetStatus.WON
                )

                won_bets = len([bet for bet in bets if bet.status == BetStatus.WON])
                lost_bets = len([bet for bet in bets if bet.status == BetStatus.LOST])
                pending_bets = len(
                    [bet for bet in bets if bet.status == BetStatus.PENDING]
                )

                win_rate = (won_bets / total_bets * 100) if total_bets > 0 else 0
                profit_loss = total_won - total_wagered

                return {
                    "total_bets": total_bets,
                    "total_wagered": total_wagered,
                    "total_won": total_won,
                    "profit_loss": profit_loss,
                    "win_rate": win_rate,
                    "won_bets": won_bets,
                    "lost_bets": lost_bets,
                    "pending_bets": pending_bets,
                    "straight_bets": len(
                        [bet for bet in bets if bet.source == BetSource.STRAIGHT]
                    ),
                    "parlay_bets": len([bet for bet in bets if bet.is_parlay]),
                    "live_bets": len([bet for bet in bets if bet.is_live]),
                    "yetai_bets": len([bet for bet in bets if bet.is_yetai_bet]),
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return {}

    def _parse_bet_selection(
        self, selection: str, bet_type: str, home_team: str, away_team: str
    ) -> Dict:
        """Parse bet selection text into structured data"""
        result = {
            "team_selection": TeamSide.NONE,
            "selected_team_name": None,
            "spread_value": None,
            "spread_selection": TeamSide.NONE,
            "total_points": None,
            "over_under_selection": OverUnder.NONE,
        }

        selection_lower = selection.lower()

        # Parse moneyline selections
        if bet_type.lower() == "moneyline":
            if home_team and home_team.lower() in selection_lower:
                result["team_selection"] = TeamSide.HOME
                result["selected_team_name"] = home_team
            elif away_team and away_team.lower() in selection_lower:
                result["team_selection"] = TeamSide.AWAY
                result["selected_team_name"] = away_team

        # Parse spread selections
        elif bet_type.lower() == "spread":
            import re

            # Look for patterns like "Team +7.5" or "Team -3.5"
            spread_match = re.search(r"([+-]?\d+\.?\d*)", selection)
            if spread_match:
                result["spread_value"] = float(spread_match.group(1))

                if home_team and home_team.lower() in selection_lower:
                    result["spread_selection"] = TeamSide.HOME
                    result["selected_team_name"] = home_team
                elif away_team and away_team.lower() in selection_lower:
                    result["spread_selection"] = TeamSide.AWAY
                    result["selected_team_name"] = away_team

        # Parse total selections
        elif bet_type.lower() == "total":
            import re

            # Look for patterns like "Over 45.5" or "Under 225.5"
            total_match = re.search(r"(\d+\.?\d*)", selection)
            if total_match:
                result["total_points"] = float(total_match.group(1))

                if "over" in selection_lower:
                    result["over_under_selection"] = OverUnder.OVER
                elif "under" in selection_lower:
                    result["over_under_selection"] = OverUnder.UNDER

        return result

    def _format_bet_response(self, bet: SimpleUnifiedBet) -> Dict:
        """Format a bet record for API response"""
        return {
            "id": bet.id,
            "user_id": bet.user_id,
            "odds_api_event_id": bet.odds_api_event_id,
            "game_id": bet.game_id,
            "bet_type": bet.bet_type.value,
            "amount": bet.amount,
            "odds": bet.odds,
            "potential_win": bet.potential_win,
            "status": bet.status.value,
            "selection": bet.selection,
            "home_team": bet.home_team,
            "away_team": bet.away_team,
            "sport": bet.sport,
            "commence_time": (
                bet.commence_time.isoformat() if bet.commence_time else None
            ),
            "placed_at": bet.placed_at.isoformat() if bet.placed_at else None,
            "settled_at": bet.settled_at.isoformat() if bet.settled_at else None,
            "result_amount": bet.result_amount,
            "source": bet.source.value,
            "bookmaker": bet.bookmaker,
            "is_parlay": bet.is_parlay,
            "is_live": bet.is_live,
            "is_yetai_bet": bet.is_yetai_bet,
            "parent_bet_id": bet.parent_bet_id,
            "leg_count": bet.leg_count,
            "leg_position": bet.leg_position,
            "total_odds": bet.total_odds,
            # Structured data fields
            "team_selection": bet.team_selection.value if bet.team_selection else None,
            "selected_team_name": bet.selected_team_name,
            "spread_value": bet.spread_value,
            "spread_selection": (
                bet.spread_selection.value if bet.spread_selection else None
            ),
            "total_points": bet.total_points,
            "over_under_selection": (
                bet.over_under_selection.value if bet.over_under_selection else None
            ),
            # Live betting fields
            "game_time_at_placement": bet.game_time_at_placement,
            "score_at_placement": bet.score_at_placement,
            "cash_out_available": bet.cash_out_available,
            "cash_out_value": bet.cash_out_value,
            # YetAI fields
            "title": bet.title,
            "description": bet.description,
            "confidence": bet.confidence,
            "tier_requirement": (
                bet.tier_requirement.value if bet.tier_requirement else None
            ),
        }

    async def _check_bet_limits(self, user_id: int, amount: float, db: Session) -> bool:
        """Check if bet amount is within user limits"""
        try:
            # Check single bet limit
            if amount > self.bet_limits["single_bet"]:
                return False

            # Check daily limit
            today = datetime.utcnow().date()
            daily_total = (
                db.query(func.sum(SimpleUnifiedBet.amount))
                .filter(
                    and_(
                        SimpleUnifiedBet.user_id == user_id,
                        SimpleUnifiedBet.placed_at >= today,
                        SimpleUnifiedBet.parent_bet_id.is_(
                            None
                        ),  # Don't count parlay legs
                    )
                )
                .scalar()
                or 0
            )

            if daily_total + amount > self.bet_limits["daily"]:
                return False

            return True

        except Exception as e:
            logger.error(f"Error checking bet limits: {e}")
            return False

    async def _get_or_create_game(self, bet_data, db: Session) -> Optional[Game]:
        """Get or create a game record"""
        try:
            game_id = getattr(bet_data, "game_id", None)
            if not game_id:
                return None

            game = db.query(Game).filter(Game.id == game_id).first()
            if game:
                return game

            # Create minimal game record if not found
            game = Game(
                id=game_id,
                home_team=getattr(bet_data, "home_team", "Unknown"),
                away_team=getattr(bet_data, "away_team", "Unknown"),
                sport_key=getattr(bet_data, "sport", "unknown"),
                sport_title=getattr(bet_data, "sport", "Unknown"),
                commence_time=getattr(bet_data, "commence_time", datetime.utcnow()),
                status="scheduled",
            )
            db.add(game)
            return game

        except Exception as e:
            logger.error(f"Error getting/creating game: {e}")
            return None

    def _calculate_potential_win(self, odds: float, amount: float) -> float:
        """Calculate potential win from American odds and bet amount"""
        if odds > 0:
            # Positive odds: amount * (odds / 100)
            return amount * (odds / 100)
        else:
            # Negative odds: amount * (100 / abs(odds))
            return amount * (100 / abs(odds))


# Global instance
simple_unified_bet_service = SimpleUnifiedBetService()
