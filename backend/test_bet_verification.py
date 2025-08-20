#!/usr/bin/env python3

import sys
sys.path.append('/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend')

import asyncio
from app.services.bet_verification_service import BetVerificationService
from app.core.config import settings

async def test_verification():
    """Test the bet verification system with our completed games"""
    
    print("🧪 Testing Bet Verification System...")
    print("This should find and resolve the test bets we just created")
    
    async with BetVerificationService() as verifier:
        print("\n📊 Running bet verification...")
        result = await verifier.verify_all_pending_bets()
        
        print(f"\n🎯 Verification Results:")
        print(f"  - Success: {result.get('success', False)}")
        print(f"  - Message: {result.get('message', 'No message')}")
        print(f"  - Verified: {result.get('verified', 0)} bets")
        print(f"  - Settled: {result.get('settled', 0)} bets")
        print(f"  - Games Checked: {result.get('games_checked', 0)}")
        
        if 'error' in result:
            print(f"  - Error: {result['error']}")
    
    print("\n✅ Verification test complete!")

if __name__ == "__main__":
    asyncio.run(test_verification())