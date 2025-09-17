import asyncio
import random
from datetime import datetime
from app.services.live_betting_service_db import (
    live_betting_service_db as live_betting_service,
)
from app.services.websocket_manager import manager
from app.models.live_bet_models import LiveGameUpdate, LiveOddsUpdate, GameStatus


class LiveBettingSimulator:
    """Simulate live games and odds updates for testing"""

    def __init__(self):
        self.active_games = {}
        self.game_timers = {}

    async def start_simulation(self):
        """Disabled to prevent fake data from appearing in live betting"""
        print("Live betting simulator disabled to prevent fake data")
        return

    async def create_live_game(self, game_data):
        """Create a live game with initial state"""
        game_update = LiveGameUpdate(
            game_id=game_data["game_id"],
            status=game_data["status"],
            home_score=game_data["home_score"],
            away_score=game_data["away_score"],
            time_remaining=game_data["time_remaining"],
            timestamp=datetime.utcnow(),
        )

        # Update in service
        live_betting_service.update_game_state(game_update)

        # Create initial odds
        odds_update = LiveOddsUpdate(
            game_id=game_data["game_id"],
            bet_type="moneyline",
            home_odds=-110,
            away_odds=-110,
            spread=-3.5,
            total=48.5,
            timestamp=datetime.utcnow(),
            is_suspended=False,
        )

        live_betting_service.update_live_odds(odds_update)

        # Store game info
        self.active_games[game_data["game_id"]] = game_data

    async def simulate_game_progress(self, game_id):
        """Simulate game progression with score updates"""
        game = self.active_games.get(game_id)
        if not game:
            return

        quarters = [
            GameStatus.FIRST_QUARTER,
            GameStatus.SECOND_QUARTER,
            GameStatus.HALFTIME,
            GameStatus.THIRD_QUARTER,
            GameStatus.FOURTH_QUARTER,
            GameStatus.FINAL,
        ]

        current_quarter_idx = 0

        while current_quarter_idx < len(quarters):
            # Wait 10-20 seconds between updates
            await asyncio.sleep(random.randint(10, 20))

            status = quarters[current_quarter_idx]

            # Update scores randomly
            if status not in [GameStatus.HALFTIME, GameStatus.FINAL]:
                if random.random() > 0.5:
                    game["home_score"] += (
                        random.choice([3, 7])
                        if game["sport"] == "NFL"
                        else random.choice([2, 3])
                    )
                else:
                    game["away_score"] += (
                        random.choice([3, 7])
                        if game["sport"] == "NFL"
                        else random.choice([2, 3])
                    )

            # Create game update
            game_update = LiveGameUpdate(
                game_id=game_id,
                status=status,
                home_score=game["home_score"],
                away_score=game["away_score"],
                time_remaining=self._get_time_remaining(status),
                timestamp=datetime.utcnow(),
            )

            # Update service
            live_betting_service.update_game_state(game_update)

            # Send WebSocket update
            await manager.broadcast(
                {
                    "type": "live_game_update",
                    "game": {
                        "game_id": game_id,
                        "status": status.value,
                        "home_team": game["home_team"],
                        "away_team": game["away_team"],
                        "home_score": game["home_score"],
                        "away_score": game["away_score"],
                        "time_remaining": game_update.time_remaining,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

            current_quarter_idx += 1

            # End simulation if game is final
            if status == GameStatus.FINAL:
                break

    async def simulate_odds_changes(self, game_id):
        """Simulate odds changes based on game state"""
        while game_id in self.active_games:
            await asyncio.sleep(random.randint(5, 15))

            game = self.active_games[game_id]
            game_state = live_betting_service.live_games.get(game_id)

            if not game_state or game_state.status == GameStatus.FINAL:
                break

            # Calculate odds based on score differential
            score_diff = game_state.home_score - game_state.away_score

            # Adjust moneyline odds
            if score_diff > 0:
                home_odds = -150 - (score_diff * 10)
                away_odds = 130 + (score_diff * 10)
            elif score_diff < 0:
                home_odds = 130 - (score_diff * 10)
                away_odds = -150 + (score_diff * 10)
            else:
                home_odds = -110
                away_odds = -110

            # Randomly suspend betting sometimes
            is_suspended = random.random() < 0.1
            suspension_reason = "Timeout" if is_suspended else None

            odds_update = LiveOddsUpdate(
                game_id=game_id,
                bet_type="moneyline",
                home_odds=home_odds,
                away_odds=away_odds,
                spread=score_diff - 3.5 if score_diff != 0 else -3.5,
                total=48.5 + (game_state.home_score + game_state.away_score) / 4,
                timestamp=datetime.utcnow(),
                is_suspended=is_suspended,
                suspension_reason=suspension_reason,
            )

            live_betting_service.update_live_odds(odds_update)

            # Send WebSocket update
            await manager.broadcast(
                {
                    "type": "live_odds_update",
                    "odds": {
                        "game_id": game_id,
                        "home_odds": home_odds,
                        "away_odds": away_odds,
                        "spread": odds_update.spread,
                        "total": odds_update.total,
                        "is_suspended": is_suspended,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

    def _get_time_remaining(self, status: GameStatus) -> str:
        """Get time remaining for a game status"""
        time_map = {
            GameStatus.FIRST_QUARTER: "12:00",
            GameStatus.SECOND_QUARTER: "8:00",
            GameStatus.HALFTIME: "Halftime",
            GameStatus.THIRD_QUARTER: "10:00",
            GameStatus.FOURTH_QUARTER: "5:00",
            GameStatus.FINAL: "Final",
        }
        return time_map.get(status, "0:00")

    async def stop_simulation(self):
        """Stop all simulations"""
        self.active_games.clear()
        # Cancel all running tasks


# Initialize simulator
live_betting_simulator = LiveBettingSimulator()
