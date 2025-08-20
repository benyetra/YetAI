#!/usr/bin/env python3

import sys
sys.path.append('/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend')

from app.core.database import SessionLocal
from app.models.database_models import Game, Bet, BetStatus, BetType, GameStatus
from datetime import datetime, timedelta
import uuid

def create_test_scenario():
    """Create a test scenario with completed games and bets that should resolve"""
    
    db = SessionLocal()
    try:
        print("🎯 Creating test scenario with completed games and resolvable bets...")
        
        # Create completed games
        completed_games = [
            {
                'id': 'completed-nfl-1',
                'sport_key': 'americanfootball_nfl',
                'sport_title': 'NFL',
                'home_team': 'Kansas City Chiefs',
                'away_team': 'Buffalo Bills', 
                'home_score': 24,
                'away_score': 17,
                'status': GameStatus.FINAL,
                'commence_time': datetime.utcnow() - timedelta(hours=2),
                'last_update': datetime.utcnow()
            },
            {
                'id': 'completed-mlb-1', 
                'sport_key': 'baseball_mlb',
                'sport_title': 'MLB',
                'home_team': 'New York Yankees',
                'away_team': 'Boston Red Sox',
                'home_score': 8,
                'away_score': 5,
                'status': GameStatus.FINAL,
                'commence_time': datetime.utcnow() - timedelta(hours=4),
                'last_update': datetime.utcnow()
            },
            {
                'id': 'completed-nba-1',
                'sport_key': 'basketball_nba', 
                'sport_title': 'NBA',
                'home_team': 'Los Angeles Lakers',
                'away_team': 'Golden State Warriors',
                'home_score': 112,
                'away_score': 108,
                'status': GameStatus.FINAL,
                'commence_time': datetime.utcnow() - timedelta(hours=6),
                'last_update': datetime.utcnow()
            }
        ]
        
        for game_data in completed_games:
            # Check if game already exists
            existing = db.query(Game).filter(Game.id == game_data['id']).first()
            if existing:
                print(f"Game {game_data['id']} already exists, updating...")
                for key, value in game_data.items():
                    setattr(existing, key, value)
            else:
                print(f"Creating new game {game_data['id']}")
                game = Game(**game_data)
                db.add(game)
        
        # Create test bets that should resolve
        test_bets = [
            {
                'id': str(uuid.uuid4()),
                'user_id': 3,  # Admin user
                'game_id': 'completed-nfl-1',
                'bet_type': BetType.MONEYLINE,
                'selection': 'Kansas City Chiefs',  # Home team won 24-17
                'odds': -150,
                'amount': 50.0,
                'potential_win': 33.33,
                'status': BetStatus.PENDING,
                'home_team': 'Kansas City Chiefs',
                'away_team': 'Buffalo Bills',
                'sport': 'americanfootball_nfl',
                'commence_time': datetime.utcnow() - timedelta(hours=2),
                'placed_at': datetime.utcnow() - timedelta(hours=3)
            },
            {
                'id': str(uuid.uuid4()),
                'user_id': 3,
                'game_id': 'completed-nfl-1', 
                'bet_type': BetType.SPREAD,
                'selection': 'Buffalo Bills +3.5',  # Bills lost by 7, didn't cover
                'odds': -110,
                'amount': 25.0,
                'potential_win': 22.73,
                'status': BetStatus.PENDING,
                'home_team': 'Kansas City Chiefs',
                'away_team': 'Buffalo Bills',
                'sport': 'americanfootball_nfl',
                'commence_time': datetime.utcnow() - timedelta(hours=2),
                'placed_at': datetime.utcnow() - timedelta(hours=3)
            },
            {
                'id': str(uuid.uuid4()),
                'user_id': 3,
                'game_id': 'completed-nfl-1',
                'bet_type': BetType.TOTAL,
                'selection': 'Over 45.5',  # Total was 41, under won
                'odds': -110,
                'amount': 20.0,
                'potential_win': 18.18,
                'status': BetStatus.PENDING,
                'home_team': 'Kansas City Chiefs',
                'away_team': 'Buffalo Bills',
                'sport': 'americanfootball_nfl',
                'commence_time': datetime.utcnow() - timedelta(hours=2),
                'placed_at': datetime.utcnow() - timedelta(hours=3)
            },
            {
                'id': str(uuid.uuid4()),
                'user_id': 3,
                'game_id': 'completed-mlb-1',
                'bet_type': BetType.MONEYLINE,
                'selection': 'New York Yankees',  # Home team won 8-5
                'odds': -120,
                'amount': 30.0,
                'potential_win': 25.0,
                'status': BetStatus.PENDING,
                'home_team': 'New York Yankees',
                'away_team': 'Boston Red Sox',
                'sport': 'baseball_mlb',
                'commence_time': datetime.utcnow() - timedelta(hours=4),
                'placed_at': datetime.utcnow() - timedelta(hours=5)
            },
            {
                'id': str(uuid.uuid4()),
                'user_id': 3,
                'game_id': 'completed-nba-1',
                'bet_type': BetType.TOTAL,
                'selection': 'Under 225.5',  # Total was 220, under won
                'odds': -105,
                'amount': 40.0,
                'potential_win': 38.10,
                'status': BetStatus.PENDING,
                'home_team': 'Los Angeles Lakers',
                'away_team': 'Golden State Warriors', 
                'sport': 'basketball_nba',
                'commence_time': datetime.utcnow() - timedelta(hours=6),
                'placed_at': datetime.utcnow() - timedelta(hours=7)
            }
        ]
        
        for bet_data in test_bets:
            bet = Bet(**bet_data)
            db.add(bet)
            print(f"Created test bet: {bet_data['selection']} on {bet_data['game_id']}")
        
        db.commit()
        print("\n✅ Test scenario created successfully!")
        print("\nExpected results when verification runs:")
        print("- Chiefs moneyline: WON (Chiefs won 24-17)")
        print("- Bills +3.5 spread: LOST (Lost by 7)")
        print("- Over 45.5 total: LOST (Total was 41)")
        print("- Yankees moneyline: WON (Yankees won 8-5)")
        print("- Under 225.5 total: WON (Total was 220)")
        
        return True
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error creating test scenario: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    create_test_scenario()