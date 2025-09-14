"""
Database-powered bet service for persistent storage
"""
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from app.core.database import get_db, SessionLocal
from app.models.database_models import User, Bet, ParlayBet, Game, BetHistory, BetLimit
from app.models.bet_models import *

logger = logging.getLogger(__name__)

class BetServiceDB:
    """Database-powered bet placement, tracking, and settlement service"""
    
    def __init__(self):
        self.bet_limits = {
            "daily": 5000,
            "weekly": 20000,
            "single_bet": 10000
        }
        
    async def place_bet(self, user_id: int, bet_data: PlaceBetRequest) -> Dict:
        """Place a single bet with database persistence"""
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
                
                # Calculate potential winnings
                potential_win = self._calculate_potential_win(
                    bet_data.amount, 
                    bet_data.odds
                )
                
                # Create bet record
                bet = Bet(
                    id=bet_id,
                    user_id=user_id,
                    game_id=game.id if game else None,
                    bet_type=bet_data.bet_type,
                    selection=bet_data.selection,
                    odds=bet_data.odds,
                    amount=bet_data.amount,
                    potential_win=potential_win,
                    status=BetStatus.PENDING,
                    placed_at=datetime.utcnow(),
                    # Include game details for better display
                    home_team=bet_data.home_team,
                    away_team=bet_data.away_team,
                    sport=bet_data.sport,
                    commence_time=bet_data.commence_time
                )
                
                db.add(bet)
                
                # Log bet history
                history = BetHistory(
                    user_id=user_id,
                    bet_id=bet_id,
                    action="placed",
                    new_status=BetStatus.PENDING.value,
                    amount=bet_data.amount,
                    bet_metadata={"bet_type": bet_data.bet_type, "selection": bet_data.selection}
                )
                db.add(history)
                
                db.commit()
                
                logger.info(f"Bet placed: {bet_id} for user {user_id}")
                
                return {
                    "success": True,
                    "bet": {
                        "id": bet.id,
                        "user_id": bet.user_id,
                        "game_id": bet.game_id,
                        "bet_type": bet.bet_type,
                        "selection": bet.selection,
                        "odds": bet.odds,
                        "amount": bet.amount,
                        "potential_win": bet.potential_win,
                        "status": bet.status,
                        "placed_at": bet.placed_at.isoformat(),
                        "home_team": bet.home_team,
                        "away_team": bet.away_team,
                        "sport": bet.sport,
                        "commence_time": bet.commence_time.isoformat() if bet.commence_time else None
                    },
                    "message": "Bet placed successfully"
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error placing bet: {e}")
            return {"success": False, "error": str(e)}
    
    async def place_parlay(self, user_id: int, parlay_data: PlaceParlayRequest) -> Dict:
        """Place a parlay bet with multiple legs"""
        try:
            if len(parlay_data.legs) < 2:
                return {"success": False, "error": "Parlay must have at least 2 legs"}
            
            if len(parlay_data.legs) > 10:
                return {"success": False, "error": "Maximum 10 legs allowed in parlay"}
            
            db = SessionLocal()
            try:
                # Check bet limits (simplified)
                if parlay_data.amount > 10000:
                    return {"success": False, "error": "Bet exceeds maximum limit of $10,000"}
                
                # Calculate parlay odds
                total_odds = 1.0
                for leg in parlay_data.legs:
                    decimal_odds = self._american_to_decimal(leg.odds)
                    total_odds *= decimal_odds
                
                # Convert back to American odds
                parlay_odds = self._decimal_to_american(total_odds)
                potential_win = (total_odds - 1) * parlay_data.amount
                
                # Generate parlay ID
                parlay_id = str(uuid.uuid4())
                
                # Create main parlay bet
                parlay_bet = ParlayBet(
                    id=parlay_id,
                    user_id=user_id,
                    amount=parlay_data.amount,
                    total_odds=parlay_odds,
                    potential_win=potential_win,
                    status=BetStatus.PENDING,
                    placed_at=datetime.utcnow(),
                    leg_count=len(parlay_data.legs)
                )
                
                db.add(parlay_bet)
                
                # Create individual leg bets
                leg_bets = []
                for leg in parlay_data.legs:
                    leg_id = str(uuid.uuid4())
                    
                    leg_bet = Bet(
                        id=leg_id,
                        user_id=user_id,
                        game_id=None,  # Set to None to avoid foreign key constraint
                        parlay_id=parlay_id,
                        bet_type=leg.bet_type,
                        selection=leg.selection,
                        odds=leg.odds,
                        amount=0,  # Individual legs don't have separate amounts
                        potential_win=0,
                        status=BetStatus.PENDING,
                        placed_at=datetime.utcnow(),
                        # Use leg data if available, otherwise None
                        home_team=getattr(leg, 'home_team', None),
                        away_team=getattr(leg, 'away_team', None),
                        sport=getattr(leg, 'sport', None),
                        commence_time=datetime.utcnow()
                    )
                    
                    db.add(leg_bet)
                    leg_bets.append(leg_bet)
                
                # Log parlay history
                history = BetHistory(
                    user_id=user_id,
                    bet_id=parlay_id,
                    action="placed",
                    new_status=BetStatus.PENDING.value,
                    amount=parlay_data.amount,
                    bet_metadata={"type": "parlay", "leg_count": len(parlay_data.legs)}
                )
                db.add(history)
                
                db.commit()
                
                logger.info(f"Parlay placed: {parlay_id} with {len(parlay_data.legs)} legs for user {user_id}")
                
                return {
                    "success": True,
                    "parlay": {
                        "id": parlay_bet.id,
                        "user_id": parlay_bet.user_id,
                        "amount": parlay_bet.amount,
                        "total_odds": parlay_bet.total_odds,
                        "potential_win": parlay_bet.potential_win,
                        "status": parlay_bet.status,
                        "placed_at": parlay_bet.placed_at.isoformat(),
                        "leg_count": parlay_bet.leg_count
                    },
                    "legs": [self._bet_to_dict(leg) for leg in leg_bets],
                    "message": f"Parlay placed with {len(parlay_data.legs)} legs"
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error placing parlay: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_bet_history(self, user_id: int, query: BetHistoryQuery) -> Dict:
        """Get user's bet history with filtering"""
        try:
            db = SessionLocal()
            try:
                # Base query for regular bets (not parlay legs)
                bet_query = db.query(Bet).filter(
                    and_(
                        Bet.user_id == user_id,
                        Bet.parlay_id.is_(None)  # Exclude parlay legs
                    )
                )
                
                # Apply filters
                if query.status:
                    bet_query = bet_query.filter(Bet.status == query.status)
                if query.bet_type:
                    bet_query = bet_query.filter(Bet.bet_type == query.bet_type)
                if query.start_date:
                    bet_query = bet_query.filter(Bet.placed_at >= query.start_date)
                if query.end_date:
                    bet_query = bet_query.filter(Bet.placed_at <= query.end_date)
                
                # Get total count
                total_count = bet_query.count()
                
                # Apply sorting and pagination
                bets = bet_query.order_by(desc(Bet.placed_at)).offset(query.offset).limit(query.limit).all()
                
                # Get parlay bets separately
                parlay_query = db.query(ParlayBet).filter(ParlayBet.user_id == user_id)
                
                if query.status:
                    parlay_query = parlay_query.filter(ParlayBet.status == query.status)
                if query.start_date:
                    parlay_query = parlay_query.filter(ParlayBet.placed_at >= query.start_date)
                if query.end_date:
                    parlay_query = parlay_query.filter(ParlayBet.placed_at <= query.end_date)
                
                parlays = parlay_query.order_by(desc(ParlayBet.placed_at)).offset(query.offset).limit(query.limit).all()
                
                # Convert to response format
                bet_list = [self._bet_to_dict(bet) for bet in bets]
                parlay_list = [self._parlay_to_dict(parlay, db) for parlay in parlays]
                
                # Combine and sort by date
                all_bets = bet_list + parlay_list
                all_bets.sort(key=lambda x: x["placed_at"], reverse=True)
                
                return {
                    "success": True,
                    "bets": all_bets[query.offset:query.offset + query.limit],
                    "total": total_count + len(parlay_list),
                    "offset": query.offset,
                    "limit": query.limit
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error fetching bet history: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_user_parlays(self, user_id: int, status: Optional[str] = None, limit: int = 50) -> Dict:
        """Get user's parlay bets with legs"""
        try:
            db = SessionLocal()
            try:
                query = db.query(ParlayBet).filter(ParlayBet.user_id == user_id)
                
                if status:
                    query = query.filter(ParlayBet.status == status)
                
                parlays = query.order_by(desc(ParlayBet.placed_at)).limit(limit).all()
                
                parlay_list = [self._parlay_to_dict(parlay, db) for parlay in parlays]
                
                return {
                    "success": True,
                    "parlays": parlay_list,
                    "total": len(parlay_list)
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error fetching user parlays: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_parlay_by_id(self, user_id: int, parlay_id: str) -> Dict:
        """Get specific parlay details by ID"""
        try:
            db = SessionLocal()
            try:
                parlay = db.query(ParlayBet).filter(
                    and_(
                        ParlayBet.id == parlay_id,
                        ParlayBet.user_id == user_id
                    )
                ).first()
                
                if not parlay:
                    return {"success": False, "error": "Parlay not found"}
                
                parlay_data = self._parlay_to_dict(parlay, db)
                
                return {"success": True, "parlay": parlay_data}
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error fetching parlay {parlay_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_bet_stats(self, user_id: int) -> Dict:
        """Get comprehensive betting statistics for a user"""
        try:
            db = SessionLocal()
            try:
                # Get all bets (excluding parlay legs)
                bets = db.query(Bet).filter(
                    and_(
                        Bet.user_id == user_id,
                        Bet.parlay_id.is_(None)
                    )
                ).all()
                
                # Get parlay bets
                parlays = db.query(ParlayBet).filter(ParlayBet.user_id == user_id).all()
                
                # Combine for statistics
                all_bets = []
                for bet in bets:
                    all_bets.append({
                        "amount": bet.amount,
                        "odds": bet.odds,
                        "status": bet.status,
                        "result_amount": bet.result_amount or 0,
                        "potential_win": bet.potential_win
                    })
                
                for parlay in parlays:
                    all_bets.append({
                        "amount": parlay.amount,
                        "odds": parlay.total_odds,
                        "status": parlay.status,
                        "result_amount": parlay.result_amount or 0,
                        "potential_win": parlay.potential_win
                    })
                
                if not all_bets:
                    return {
                        "success": True,
                        "stats": BetStats(
                            total_bets=0,
                            total_wagered=0,
                            total_won=0,
                            total_lost=0,
                            net_profit=0,
                            win_rate=0,
                            average_bet=0,
                            average_odds=0,
                            best_win=0,
                            worst_loss=0,
                            current_streak=0,
                            longest_win_streak=0,
                            longest_loss_streak=0
                        ).dict()
                    }
                
                # Calculate statistics
                total_bets = len(all_bets)
                total_wagered = sum(bet["amount"] for bet in all_bets)
                total_won = sum(bet["result_amount"] for bet in all_bets if bet["status"] == BetStatus.WON)
                total_lost = sum(bet["amount"] for bet in all_bets if bet["status"] == BetStatus.LOST)
                wins = len([bet for bet in all_bets if bet["status"] == BetStatus.WON])
                losses = len([bet for bet in all_bets if bet["status"] == BetStatus.LOST])
                
                win_rate = (wins / total_bets * 100) if total_bets > 0 else 0
                average_bet = total_wagered / total_bets if total_bets > 0 else 0
                average_odds = sum(bet["odds"] for bet in all_bets) / total_bets if total_bets > 0 else 0
                net_profit = total_won - total_lost
                
                best_win = max((bet["result_amount"] for bet in all_bets if bet["status"] == BetStatus.WON), default=0)
                worst_loss = max((bet["amount"] for bet in all_bets if bet["status"] == BetStatus.LOST), default=0)
                
                stats = BetStats(
                    total_bets=total_bets,
                    total_wagered=round(total_wagered, 2),
                    total_won=round(total_won, 2),
                    total_lost=round(total_lost, 2),
                    net_profit=round(net_profit, 2),
                    win_rate=round(win_rate, 2),
                    average_bet=round(average_bet, 2),
                    average_odds=round(average_odds, 2),
                    best_win=round(best_win, 2),
                    worst_loss=round(worst_loss, 2),
                    current_streak=0,  # Would need more complex calculation
                    longest_win_streak=0,  # Would need more complex calculation
                    longest_loss_streak=0  # Would need more complex calculation
                )
                
                return {"success": True, "stats": stats.dict()}
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error calculating stats: {e}")
            return {"success": False, "error": str(e)}
    
    def _bet_to_dict(self, bet: Bet) -> Dict:
        """Convert Bet model to dictionary"""
        return {
            "id": bet.id,
            "user_id": bet.user_id,
            "game_id": bet.game_id,
            "bet_type": bet.bet_type,
            "selection": bet.selection,
            "odds": bet.odds,
            "amount": bet.amount,
            "potential_win": bet.potential_win,
            "status": bet.status,
            "placed_at": bet.placed_at.isoformat(),
            "settled_at": bet.settled_at.isoformat() if bet.settled_at else None,
            "result_amount": bet.result_amount,
            "home_team": bet.home_team,
            "away_team": bet.away_team,
            "sport": bet.sport,
            "commence_time": bet.commence_time.isoformat() if bet.commence_time else None,
            "parlay_id": bet.parlay_id
        }
    
    def _parlay_to_dict(self, parlay: ParlayBet, db: Session) -> Dict:
        """Convert ParlayBet model to dictionary with legs"""
        # Get legs with game information
        legs = db.query(Bet).filter(Bet.parlay_id == parlay.id).all()
        
        # Enhance legs with game information if missing
        enhanced_legs = []
        for leg in legs:
            leg_dict = self._bet_to_dict(leg)
            
            # If leg doesn't have team info but has game_id, get it from Game table
            if not leg_dict.get('home_team') and leg_dict.get('game_id'):
                game = db.query(Game).filter(Game.id == leg_dict['game_id']).first()
                if game:
                    leg_dict['home_team'] = game.home_team
                    leg_dict['away_team'] = game.away_team
                    leg_dict['sport'] = game.sport_key
                    leg_dict['commence_time'] = game.commence_time.isoformat() if game.commence_time else None
            
            enhanced_legs.append(leg_dict)
        
        return {
            "id": parlay.id,
            "user_id": parlay.user_id,
            "amount": parlay.amount,
            "total_odds": parlay.total_odds,
            "potential_win": parlay.potential_win,
            "status": parlay.status,
            "placed_at": parlay.placed_at.isoformat(),
            "settled_at": parlay.settled_at.isoformat() if parlay.settled_at else None,
            "result_amount": parlay.result_amount,
            "leg_count": parlay.leg_count,
            "legs": enhanced_legs,
            "bet_type": "parlay"  # For compatibility
        }
    
    async def _get_or_create_game(self, bet_data: PlaceBetRequest, db: Session) -> Optional[Game]:
        """Get or create game record"""
        if not bet_data.game_id:
            return None
            
        game = db.query(Game).filter(Game.id == bet_data.game_id).first()
        
        if not game and bet_data.home_team and bet_data.away_team:
            game = Game(
                id=bet_data.game_id,
                sport_key=bet_data.sport or "unknown",
                sport_title=bet_data.sport or "Unknown",
                home_team=bet_data.home_team,
                away_team=bet_data.away_team,
                commence_time=bet_data.commence_time or datetime.utcnow()
            )
            db.add(game)
            
        return game
    
    async def _get_or_create_game_from_leg(self, leg, db: Session) -> Optional[Game]:
        """Get or create game record from parlay leg"""
        if not hasattr(leg, 'game_id') or not leg.game_id:
            return None
            
        game = db.query(Game).filter(Game.id == leg.game_id).first()
        
        if not game:
            # Use team information from leg data if available
            sport_key = leg.sport if hasattr(leg, 'sport') and leg.sport else "unknown"
            home_team = leg.home_team if hasattr(leg, 'home_team') and leg.home_team else "TBD"
            away_team = leg.away_team if hasattr(leg, 'away_team') and leg.away_team else "TBD"
            commence_time = self._parse_datetime(leg.commence_time) if hasattr(leg, 'commence_time') and leg.commence_time else datetime.utcnow()
            
            # Fallback: try to extract sport from game_id pattern if no sport provided
            if sport_key == "unknown" and leg.game_id.startswith('nfl-'):
                sport_key = "americanfootball_nfl"
            
            game = Game(
                id=leg.game_id,
                sport_key=sport_key,
                sport_title=sport_key.replace('_', ' ').title(),
                home_team=home_team,
                away_team=away_team,
                commence_time=commence_time
            )
            
            try:
                db.add(game)
                db.flush()  # Flush to catch unique constraint violations
            except Exception as e:
                # Handle unique constraint violation - another transaction created the game
                db.rollback()
                game = db.query(Game).filter(Game.id == leg.game_id).first()
                if not game:
                    # If still not found, re-raise the error
                    raise e
                    
        return game
    
    def _calculate_potential_win(self, amount: float, odds: float) -> float:
        """Calculate potential winnings from American odds"""
        if odds > 0:
            return amount * (odds / 100)
        else:
            return amount * (100 / abs(odds))
    
    def _american_to_decimal(self, odds: float) -> float:
        """Convert American odds to decimal"""
        if odds > 0:
            return (odds / 100) + 1
        else:
            return (100 / abs(odds)) + 1
    
    def _decimal_to_american(self, odds: float) -> int:
        """Convert decimal odds to American"""
        if odds >= 2:
            return round((odds - 1) * 100)
        else:
            return round(-100 / (odds - 1))
    
    async def _check_bet_limits(self, user_id: int, amount: float, db: Session) -> bool:
        """Check if bet amount is within user limits"""
        if amount > self.bet_limits["single_bet"]:
            return False
        
        # Check daily limit
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_total = await self._get_period_total(user_id, today_start, db)
        if today_total + amount > self.bet_limits["daily"]:
            return False
        
        # Check weekly limit
        week_start = today_start - timedelta(days=7)
        week_total = await self._get_period_total(user_id, week_start, db)
        if week_total + amount > self.bet_limits["weekly"]:
            return False
        
        return True
    
    async def _get_period_total(self, user_id: int, start_date: datetime, db: Session) -> float:
        """Get total bet amount for a period"""
        # Regular bets
        bet_total = db.query(Bet).filter(
            and_(
                Bet.user_id == user_id,
                Bet.placed_at >= start_date,
                Bet.parlay_id.is_(None)  # Don't count parlay legs
            )
        ).with_entities(Bet.amount).all()
        
        # Parlay bets
        parlay_total = db.query(ParlayBet).filter(
            and_(
                ParlayBet.user_id == user_id,
                ParlayBet.placed_at >= start_date
            )
        ).with_entities(ParlayBet.amount).all()
        
        total = sum(bet.amount for bet in bet_total) + sum(parlay.amount for parlay in parlay_total)
        return total
    
    def _parse_datetime(self, datetime_str: str) -> datetime:
        """Parse datetime string with various formats"""
        try:
            # Handle ISO format with Z
            if datetime_str.endswith('Z'):
                datetime_str = datetime_str.replace('Z', '+00:00')
            return datetime.fromisoformat(datetime_str)
        except ValueError:
            # Fallback to current time if parsing fails
            return datetime.utcnow()
    
    async def cancel_bet(self, user_id: int, bet_id: str) -> Dict:
        """Cancel a pending bet"""
        try:
            db = SessionLocal()
            try:
                # Find the bet
                bet = db.query(Bet).filter(
                    and_(
                        Bet.id == bet_id,
                        Bet.user_id == user_id
                    )
                ).first()
                
                if not bet:
                    return {"success": False, "error": "Bet not found"}
                
                if bet.status != BetStatus.PENDING:
                    return {"success": False, "error": "Can only cancel pending bets"}
                
                # Check if game has started (would need real game data)
                # For now, allow cancellation if placed within last 5 minutes
                time_since_placed = datetime.utcnow() - bet.placed_at.replace(tzinfo=None)
                if time_since_placed > timedelta(minutes=5):
                    return {"success": False, "error": "Cancellation window has passed"}
                
                # Update bet status
                bet.status = BetStatus.CANCELLED
                bet.settled_at = datetime.utcnow()
                
                db.commit()
                
                return {"success": True, "message": "Bet cancelled successfully"}
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error cancelling bet: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_active_live_bets(self, user_id: int) -> List[Dict]:
        """Get user's active live bets (pending bets for live games)"""
        try:
            db = SessionLocal()
            try:
                # Get active live bets - these are bets that are still pending
                # and are for games that might be in progress
                active_bets = db.query(Bet).filter(
                    and_(
                        Bet.user_id == user_id,
                        Bet.status == BetStatus.PENDING,
                        Bet.parlay_id.is_(None)  # Exclude parlay legs
                    )
                ).order_by(desc(Bet.placed_at)).all()
                
                # Also get active parlay bets
                active_parlays = db.query(ParlayBet).filter(
                    and_(
                        ParlayBet.user_id == user_id,
                        ParlayBet.status == BetStatus.PENDING
                    )
                ).order_by(desc(ParlayBet.placed_at)).all()
                
                # Convert to response format
                bet_list = [self._bet_to_dict(bet) for bet in active_bets]
                parlay_list = [self._parlay_to_dict(parlay, db) for parlay in active_parlays]
                
                # Combine and sort by placed_at
                all_active = bet_list + parlay_list
                all_active.sort(key=lambda x: x["placed_at"], reverse=True)
                
                return all_active
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error fetching active live bets: {e}")
            return []

    async def simulate_bet_results(self, user_id: int) -> Dict:
        """Simulate some bet results for demo purposes"""
        try:
            db = SessionLocal()
            try:
                # Get pending bets for user
                pending_bets = db.query(Bet).filter(
                    and_(
                        Bet.user_id == user_id,
                        Bet.status == BetStatus.PENDING
                    )
                ).limit(5).all()
                
                if not pending_bets:
                    return {"success": False, "error": "No pending bets found"}
                
                import random
                results_set = 0
                
                for bet in pending_bets:
                    # Randomly set results (70% win rate for demo)
                    if random.random() < 0.7:
                        bet.status = BetStatus.WON
                        bet.result_amount = bet.potential_win
                    else:
                        bet.status = BetStatus.LOST
                        bet.result_amount = 0
                    
                    bet.settled_at = datetime.utcnow()
                    results_set += 1
                
                db.commit()
                
                return {
                    "success": True,
                    "message": f"Simulated results for {results_set} bets"
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error simulating results: {e}")
            return {"success": False, "error": str(e)}

# Initialize service
bet_service_db = BetServiceDB()