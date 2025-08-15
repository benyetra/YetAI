from fastapi import WebSocket
from typing import Dict, List, Set
import json
import asyncio
import logging
from datetime import datetime
import random

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manage WebSocket connections and live updates"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_subscriptions: Dict[str, Set[str]] = {}  # user_id -> set of game_ids
        self.game_subscribers: Dict[str, Set[str]] = {}  # game_id -> set of user_ids
        
    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept new WebSocket connection"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.user_subscriptions[user_id] = set()
        logger.info(f"User {user_id} connected via WebSocket")
        
        # Send initial connection confirmation
        await self.send_personal_message(
            {"type": "connection", "status": "connected", "timestamp": datetime.utcnow().isoformat()},
            user_id
        )
    
    def disconnect(self, user_id: str):
        """Remove WebSocket connection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            
            # Clean up subscriptions
            if user_id in self.user_subscriptions:
                for game_id in self.user_subscriptions[user_id]:
                    if game_id in self.game_subscribers:
                        self.game_subscribers[game_id].discard(user_id)
                del self.user_subscriptions[user_id]
            
            logger.info(f"User {user_id} disconnected")
    
    async def subscribe_to_game(self, user_id: str, game_id: str):
        """Subscribe user to game updates"""
        if user_id in self.user_subscriptions:
            self.user_subscriptions[user_id].add(game_id)
            
            if game_id not in self.game_subscribers:
                self.game_subscribers[game_id] = set()
            self.game_subscribers[game_id].add(user_id)
            
            await self.send_personal_message(
                {"type": "subscription", "game_id": game_id, "status": "subscribed"},
                user_id
            )
            logger.info(f"User {user_id} subscribed to game {game_id}")
    
    async def unsubscribe_from_game(self, user_id: str, game_id: str):
        """Unsubscribe user from game updates"""
        if user_id in self.user_subscriptions:
            self.user_subscriptions[user_id].discard(game_id)
            
            if game_id in self.game_subscribers:
                self.game_subscribers[game_id].discard(user_id)
            
            await self.send_personal_message(
                {"type": "subscription", "game_id": game_id, "status": "unsubscribed"},
                user_id
            )
            logger.info(f"User {user_id} unsubscribed from game {game_id}")
    
    async def send_personal_message(self, message: dict, user_id: str):
        """Send message to specific user"""
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {user_id}: {e}")
                self.disconnect(user_id)
    
    async def broadcast_game_update(self, game_id: str, update: dict):
        """Broadcast update to all subscribers of a game"""
        if game_id in self.game_subscribers:
            disconnected_users = []
            
            for user_id in self.game_subscribers[game_id]:
                if user_id in self.active_connections:
                    try:
                        await self.active_connections[user_id].send_json({
                            "type": "game_update",
                            "game_id": game_id,
                            "data": update,
                            "timestamp": datetime.utcnow().isoformat()
                        })
                    except Exception as e:
                        logger.error(f"Error broadcasting to {user_id}: {e}")
                        disconnected_users.append(user_id)
            
            # Clean up disconnected users
            for user_id in disconnected_users:
                self.disconnect(user_id)
    
    async def send_odds_update(self, game_id: str, odds_data: dict):
        """Send live odds update for a game"""
        update = {
            "home_odds": odds_data.get("home_odds"),
            "away_odds": odds_data.get("away_odds"),
            "spread": odds_data.get("spread"),
            "total": odds_data.get("total"),
            "movement": odds_data.get("movement", "stable"),  # up, down, stable
            "last_updated": datetime.utcnow().isoformat()
        }
        await self.broadcast_game_update(game_id, update)
        logger.debug(f"Sent odds update for game {game_id}")
    
    async def send_bet_notification(self, user_id: str, notification: dict):
        """Send bet-related notification to user"""
        await self.send_personal_message({
            "type": "bet_notification",
            "data": notification,
            "timestamp": datetime.utcnow().isoformat()
        }, user_id)
    
    async def send_score_update(self, game_id: str, score_data: dict):
        """Send live score update for a game"""
        update = {
            "home_score": score_data.get("home_score", 0),
            "away_score": score_data.get("away_score", 0),
            "quarter": score_data.get("quarter", 1),
            "time_remaining": score_data.get("time_remaining", "15:00"),
            "game_status": score_data.get("game_status", "live")
        }
        await self.broadcast_game_update(game_id, update)
        logger.debug(f"Sent score update for game {game_id}")
    
    def get_connection_stats(self):
        """Get current connection statistics"""
        return {
            "total_connections": len(self.active_connections),
            "total_subscriptions": sum(len(subs) for subs in self.user_subscriptions.values()),
            "active_games": len(self.game_subscribers),
            "connected_users": list(self.active_connections.keys())
        }

# Global connection manager
manager = ConnectionManager()

# Background task to simulate live odds updates
async def simulate_odds_updates():
    """Simulate live odds changes (replace with real data feed)"""
    while True:
        await asyncio.sleep(10)  # Update every 10 seconds
        
        # Get games that have active subscribers
        active_games = list(manager.game_subscribers.keys())
        
        for game_id in active_games:
            if manager.game_subscribers[game_id]:  # Only update if someone is subscribed
                # Generate random odds movement
                movement_type = random.choice(["up", "down", "stable", "stable", "stable"])
                
                # Simulate realistic odds changes
                base_odds = -110
                spread_change = random.uniform(-0.5, 0.5)
                total_change = random.uniform(-1.0, 1.0)
                
                odds_update = {
                    "home_odds": base_odds + random.randint(-10, 10),
                    "away_odds": base_odds + random.randint(-10, 10),
                    "spread": round(random.uniform(-7, 7) + spread_change, 1),
                    "total": round(random.uniform(40, 55) + total_change, 1),
                    "movement": movement_type
                }
                
                await manager.send_odds_update(game_id, odds_update)

# Background task to simulate live score updates
async def simulate_score_updates():
    """Simulate live score changes for active games"""
    while True:
        await asyncio.sleep(30)  # Update every 30 seconds
        
        # Get games that have active subscribers
        active_games = list(manager.game_subscribers.keys())
        
        for game_id in active_games:
            if manager.game_subscribers[game_id]:  # Only update if someone is subscribed
                # Simulate score progression
                score_update = {
                    "home_score": random.randint(0, 35),
                    "away_score": random.randint(0, 35),
                    "quarter": random.randint(1, 4),
                    "time_remaining": f"{random.randint(0, 14)}:{random.randint(10, 59)}",
                    "game_status": random.choice(["live", "live", "live", "halftime"])
                }
                
                await manager.send_score_update(game_id, score_update)