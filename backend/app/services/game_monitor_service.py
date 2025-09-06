"""
Game Monitor Service - Monitors games and triggers immediate bet verification when games complete

This service:
1. Monitors active games with pending bets
2. Checks for game completion more frequently during game times
3. Triggers immediate bet verification when games finish
4. Reduces unnecessary API calls by tracking game states
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.core.database import SessionLocal
from app.models.database_models import Game, Bet, ParlayBet, GameStatus, BetStatus
from app.services.odds_api_service import OddsAPIService
from app.services.bet_verification_service import BetVerificationService
from app.core.config import settings

logger = logging.getLogger(__name__)

class GameMonitorService:
    """Service for monitoring active games and triggering bet verification"""
    
    def __init__(self):
        self.monitoring_task: Optional[asyncio.Task] = None
        self.active_games: Set[str] = set()
        self.recently_completed: Dict[str, datetime] = {}  # Track recently completed games
        self._running = False
        self._stop_event = asyncio.Event()
        
    def start(self) -> None:
        """Start the game monitoring service"""
        if self._running:
            logger.warning("Game monitor is already running")
            return
            
        self._stop_event.clear()
        self.monitoring_task = asyncio.create_task(self._monitor_games())
        self._running = True
        logger.info("Started game monitoring service")
    
    def stop(self) -> None:
        """Stop the game monitoring service"""
        if not self._running:
            return
            
        self._stop_event.set()
        if self.monitoring_task:
            self.monitoring_task.cancel()
        self._running = False
        logger.info("Stopped game monitoring service")
    
    async def _monitor_games(self) -> None:
        """Main monitoring loop"""
        logger.info("Game monitoring service started")
        
        while not self._stop_event.is_set():
            try:
                # Get games with pending bets
                games_to_monitor = await self._get_games_with_pending_bets()
                
                if games_to_monitor:
                    logger.info(f"Monitoring {len(games_to_monitor)} active games with pending bets")
                    
                    # Check game statuses
                    completed_games = await self._check_game_statuses(games_to_monitor)
                    
                    if completed_games:
                        logger.info(f"Found {len(completed_games)} newly completed games")
                        # Trigger immediate bet verification for completed games
                        await self._trigger_verification_for_games(completed_games)
                
                # Clean up old completed games from tracking
                self._cleanup_completed_games()
                
                # Wait before next check (more frequent than regular scheduler)
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                logger.info("Game monitor cancelled")
                break
            except Exception as e:
                logger.error(f"Error in game monitor loop: {e}")
                await asyncio.sleep(30)  # Wait 30 seconds on error
    
    async def _get_games_with_pending_bets(self) -> List[str]:
        """Get list of game IDs that have pending bets"""
        db = SessionLocal()
        try:
            # Get game IDs from pending individual bets
            pending_bet_games = db.query(Bet.game_id).filter(
                and_(
                    Bet.status == BetStatus.PENDING,
                    Bet.game_id.isnot(None),
                    Bet.parlay_id.is_(None)
                )
            ).distinct().all()
            
            game_ids = set(game_id[0] for game_id in pending_bet_games)
            
            # Get game IDs from pending parlay legs
            parlay_legs = db.query(Bet.game_id).filter(
                and_(
                    Bet.status == BetStatus.PENDING,
                    Bet.game_id.isnot(None),
                    Bet.parlay_id.isnot(None)
                )
            ).distinct().all()
            
            game_ids.update(game_id[0] for game_id in parlay_legs)
            
            # Filter out recently completed games (avoid checking them too frequently)
            active_game_ids = []
            for game_id in game_ids:
                if game_id not in self.recently_completed:
                    # Check if game is not already marked as final in database
                    game = db.query(Game).filter(Game.id == game_id).first()
                    if not game or game.status != GameStatus.FINAL:
                        active_game_ids.append(game_id)
            
            return active_game_ids
            
        finally:
            db.close()
    
    async def _check_game_statuses(self, game_ids: List[str]) -> List[str]:
        """Check status of games and return newly completed ones"""
        if not game_ids:
            return []
            
        newly_completed = []
        
        # Group games by sport for efficient API calls
        games_by_sport = {}
        db = SessionLocal()
        
        try:
            for game_id in game_ids:
                game = db.query(Game).filter(Game.id == game_id).first()
                if game and game.sport_key:
                    sport = game.sport_key
                    if sport not in games_by_sport:
                        games_by_sport[sport] = []
                    games_by_sport[sport].append(game_id)
        finally:
            db.close()
        
        # Check each sport's games
        async with OddsAPIService(settings.ODDS_API_KEY) as odds_service:
            for sport, sport_game_ids in games_by_sport.items():
                try:
                    # Get recent scores for this sport
                    scores = await odds_service.get_scores(sport, days_from=1)
                    
                    for score in scores:
                        if score.id in sport_game_ids and score.completed:
                            # Check if this is newly completed
                            if score.id not in self.recently_completed:
                                newly_completed.append(score.id)
                                self.recently_completed[score.id] = datetime.utcnow()
                                
                                # Update game in database
                                await self._update_game_status(score)
                                
                except Exception as e:
                    logger.error(f"Error checking scores for sport {sport}: {e}")
                    continue
        
        return newly_completed
    
    async def _update_game_status(self, score) -> None:
        """Update game status in database"""
        db = SessionLocal()
        try:
            game = db.query(Game).filter(Game.id == score.id).first()
            if game:
                game.home_score = score.home_score
                game.away_score = score.away_score
                game.status = GameStatus.FINAL
                game.last_update = datetime.utcnow()
                db.commit()
                logger.info(f"Updated game {score.id} status to FINAL: {score.away_team} {score.away_score} - {score.home_team} {score.home_score}")
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating game {score.id} status: {e}")
        finally:
            db.close()
    
    async def _trigger_verification_for_games(self, game_ids: List[str]) -> None:
        """Trigger bet verification for specific completed games"""
        try:
            logger.info(f"Triggering immediate bet verification for {len(game_ids)} completed games")
            
            # Get all pending bets for these games
            db = SessionLocal()
            try:
                # Get individual bets
                pending_bets = db.query(Bet).filter(
                    and_(
                        Bet.game_id.in_(game_ids),
                        Bet.status == BetStatus.PENDING,
                        Bet.parlay_id.is_(None)
                    )
                ).all()
                
                # Get parlays with legs in these games
                parlay_ids = db.query(Bet.parlay_id).filter(
                    and_(
                        Bet.game_id.in_(game_ids),
                        Bet.status == BetStatus.PENDING,
                        Bet.parlay_id.isnot(None)
                    )
                ).distinct().all()
                
                parlay_ids = [p[0] for p in parlay_ids]
                pending_parlays = db.query(ParlayBet).filter(
                    ParlayBet.id.in_(parlay_ids)
                ).all() if parlay_ids else []
                
            finally:
                db.close()
            
            if not pending_bets and not pending_parlays:
                logger.info("No pending bets found for completed games")
                return
            
            # Run verification
            async with BetVerificationService() as verification_service:
                result = await verification_service.verify_all_pending_bets()
                
                if result.get("success"):
                    logger.info(f"Immediate verification completed: {result.get('message')}")
                else:
                    logger.error(f"Immediate verification failed: {result.get('error')}")
                    
        except Exception as e:
            logger.error(f"Error triggering verification for completed games: {e}")
    
    def _cleanup_completed_games(self) -> None:
        """Remove old entries from recently completed tracking"""
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        
        # Remove games completed more than 1 hour ago
        old_games = [
            game_id for game_id, completed_time in self.recently_completed.items()
            if completed_time < cutoff_time
        ]
        
        for game_id in old_games:
            del self.recently_completed[game_id]
        
        if old_games:
            logger.debug(f"Cleaned up {len(old_games)} old completed games from tracking")

# Global instance
game_monitor = GameMonitorService()

def init_game_monitor():
    """Initialize the game monitor (called from main.py)"""
    try:
        game_monitor.start()
        logger.info("Game monitor service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize game monitor service: {e}")

def cleanup_game_monitor():
    """Cleanup game monitor (called from main.py shutdown)"""
    try:
        game_monitor.stop()
        logger.info("Game monitor service stopped successfully")
    except Exception as e:
        logger.error(f"Error stopping game monitor service: {e}")