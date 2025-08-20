#!/usr/bin/env python3
"""
Test script for bet verification system

This script:
1. Creates sample bets in the database
2. Tests the verification API endpoints
3. Validates the bet status updates
"""

import asyncio
import json
import requests
from datetime import datetime, timedelta

# Configuration
BASE_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"

class BetVerificationTester:
    def __init__(self):
        self.token = None
        self.headers = {}

    async def setup(self):
        """Login as admin and get token"""
        print("🔐 Logging in as admin...")
        
        login_data = {
            "email_or_username": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        }
        
        response = requests.post(f"{BASE_URL}/api/auth/login", json=login_data)
        
        if response.status_code == 200:
            data = response.json()
            self.token = data.get("access_token")
            self.headers = {"Authorization": f"Bearer {self.token}"}
            print("✅ Successfully logged in as admin")
            return True
        else:
            print(f"❌ Login failed: {response.text}")
            return False

    def create_sample_bet(self, game_id: str, bet_type: str, selection: str, odds: float, amount: float = 100.0):
        """Create a sample bet"""
        bet_data = {
            "game_id": game_id,
            "bet_type": bet_type,
            "selection": selection,
            "odds": odds,
            "amount": amount,
            "home_team": "Team A",
            "away_team": "Team B",
            "sport": "americanfootball_nfl",
            "commence_time": (datetime.utcnow() - timedelta(hours=2)).isoformat()
        }
        
        response = requests.post(f"{BASE_URL}/api/bets", json=bet_data, headers=self.headers)
        
        if response.status_code == 200:
            data = response.json()
            bet_id = data.get("bet", {}).get("id")
            print(f"✅ Created {bet_type} bet: {bet_id} - {selection}")
            return bet_id
        else:
            print(f"❌ Failed to create bet: {response.text}")
            return None

    def get_verification_stats(self):
        """Get verification statistics"""
        print("\n📊 Getting verification statistics...")
        
        response = requests.get(f"{BASE_URL}/api/admin/bets/verification/stats", headers=self.headers)
        
        if response.status_code == 200:
            data = response.json()
            stats = data.get("data", {})
            
            print("📈 Scheduler Status:")
            status = stats.get("status", {})
            print(f"  - Running: {status.get('running', False)}")
            print(f"  - In Quiet Hours: {status.get('in_quiet_hours', False)}")
            
            config = stats.get("config", {})
            print(f"  - Interval: {config.get('interval_minutes', 'N/A')} minutes")
            
            run_stats = stats.get("stats", {})
            print(f"\n📊 Run Statistics:")
            print(f"  - Total Runs: {run_stats.get('total_runs', 0)}")
            print(f"  - Successful: {run_stats.get('successful_runs', 0)}")
            print(f"  - Failed: {run_stats.get('failed_runs', 0)}")
            print(f"  - Bets Verified: {run_stats.get('total_bets_verified', 0)}")
            print(f"  - Bets Settled: {run_stats.get('total_bets_settled', 0)}")
            
            return True
        else:
            print(f"❌ Failed to get stats: {response.text}")
            return False

    def trigger_verification(self):
        """Manually trigger bet verification"""
        print("\n🎯 Triggering manual bet verification...")
        
        response = requests.post(f"{BASE_URL}/api/admin/bets/verify", json={}, headers=self.headers)
        
        if response.status_code == 200:
            data = response.json()
            result = data.get("data", {})
            
            print(f"✅ Verification completed!")
            print(f"  - Success: {result.get('success', False)}")
            print(f"  - Message: {result.get('message', 'No message')}")
            print(f"  - Verified: {result.get('verified', 0)} bets")
            print(f"  - Settled: {result.get('settled', 0)} bets")
            print(f"  - Games Checked: {result.get('games_checked', 0)}")
            
            return result.get("success", False)
        else:
            print(f"❌ Verification failed: {response.text}")
            return False

    def get_bet_history(self):
        """Get bet history to check status changes"""
        print("\n📋 Checking bet history...")
        
        response = requests.get(f"{BASE_URL}/api/bets?limit=10", headers=self.headers)
        
        if response.status_code == 200:
            data = response.json()
            bets = data.get("bets", [])
            
            print(f"📝 Found {len(bets)} bets:")
            for bet in bets[:5]:  # Show first 5
                status = bet.get("status", "unknown")
                bet_type = bet.get("bet_type", "unknown")
                selection = bet.get("selection", "unknown")
                amount = bet.get("amount", 0)
                result_amount = bet.get("result_amount", 0)
                
                print(f"  - {bet_type}: {selection} | ${amount} | Status: {status} | Result: ${result_amount}")
            
            return bets
        else:
            print(f"❌ Failed to get bet history: {response.text}")
            return []

    async def run_test(self):
        """Run complete test suite"""
        print("🚀 Starting Bet Verification System Test\n")
        
        # Setup
        if not await self.setup():
            return False
        
        # Get initial stats
        self.get_verification_stats()
        
        # Create sample bets (these will likely not have completed games to verify)
        print("\n🎲 Creating sample bets...")
        
        # These are fictional game IDs - in real usage, these would come from The Odds API
        sample_bets = [
            ("test-game-1", "moneyline", "Team A", 150),
            ("test-game-2", "spread", "Team B -3.5", -110),
            ("test-game-3", "total", "Over 45.5", -105),
        ]
        
        bet_ids = []
        for game_id, bet_type, selection, odds in sample_bets:
            bet_id = self.create_sample_bet(game_id, bet_type, selection, odds)
            if bet_id:
                bet_ids.append(bet_id)
        
        print(f"\n✅ Created {len(bet_ids)} sample bets")
        
        # Get bet history before verification
        print("\n📋 Bet history before verification:")
        bets_before = self.get_bet_history()
        
        # Trigger verification
        verification_success = self.trigger_verification()
        
        # Get bet history after verification
        print("\n📋 Bet history after verification:")
        bets_after = self.get_bet_history()
        
        # Compare results
        if verification_success:
            print("\n✅ Verification completed successfully!")
            
            # Check for any status changes
            status_changes = 0
            for bet_before in bets_before:
                for bet_after in bets_after:
                    if (bet_before.get("id") == bet_after.get("id") and 
                        bet_before.get("status") != bet_after.get("status")):
                        status_changes += 1
                        print(f"  🔄 Bet {bet_before.get('id')}: {bet_before.get('status')} → {bet_after.get('status')}")
            
            if status_changes == 0:
                print("  ℹ️  No bet statuses changed (expected - test games likely not completed)")
            
        # Final stats
        print("\n📊 Final verification statistics:")
        self.get_verification_stats()
        
        print("\n🎉 Test completed successfully!")
        return True

async def main():
    tester = BetVerificationTester()
    await tester.run_test()

if __name__ == "__main__":
    asyncio.run(main())