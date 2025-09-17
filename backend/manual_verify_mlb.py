#!/usr/bin/env python3

import sys

sys.path.append("/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend")

import asyncio
from app.services.bet_verification_service import BetVerificationService
from app.core.config import settings


async def manual_verify_mlb():
    print("🔍 Manual MLB Bet Verification Test...")
    print(
        "This will test the verification system specifically for MLB games from last night"
    )

    async with BetVerificationService() as verifier:
        print("\n📊 Running bet verification...")
        result = await verifier.verify_all_pending_bets()

        print(f"\nResults:")
        print(f"  - Success: {result.get('success', False)}")
        print(f"  - Message: {result.get('message', 'No message')}")
        print(f"  - Verified: {result.get('verified', 0)} bets")
        print(f"  - Settled: {result.get('settled', 0)} bets")
        print(f"  - Games Checked: {result.get('games_checked', 0)}")

        if "error" in result:
            print(f"  - Error: {result['error']}")

    print("\n✅ Manual verification complete!")


if __name__ == "__main__":
    asyncio.run(manual_verify_mlb())
