#!/usr/bin/env python3
"""Test bet verification manually"""

import sys
import asyncio
sys.path.append("/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend")

from app.services.bet_verification_service import BetVerificationService

async def test_verification():
    """Test bet verification"""
    print("Testing bet verification...")

    async with BetVerificationService() as verification_service:
        result = await verification_service.verify_all_pending_bets()
        print(f"Verification result: {result}")

        if result.get("success"):
            print(f"✅ Success: {result.get('message')}")
            print(f"   Verified: {result.get('verified', 0)} bets")
            print(f"   Settled: {result.get('settled', 0)} bets")
            print(f"   Games checked: {result.get('games_checked', 0)}")
        else:
            print(f"❌ Error: {result.get('error', 'Unknown error')}")

if __name__ == "__main__":
    asyncio.run(test_verification())