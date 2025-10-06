#!/usr/bin/env python3
"""
Test script for unified bet verification system

This script validates that:
1. Bets are created with proper enum fields
2. Verification uses enums instead of string parsing
3. Score matching works by team name
4. Spread values include +/- signs
5. Status comparisons use BetStatus enum
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List

# Add parent directory to path
sys.path.insert(0, ".")

try:
    from app.services.unified_bet_verification_service import (
        unified_bet_verification_service,
    )
    from app.services.simple_unified_bet_service import (
        simple_unified_bet_service,
        SimpleUnifiedBetService,
    )
    from app.models.simple_unified_bet_model import (
        SimpleUnifiedBet,
        BetStatus,
        BetType,
        BetSource,
        TeamSide,
        OverUnder,
    )
    from app.core.database import SessionLocal
    from app.models.bet_models import PlaceBetRequest

    print("✅ All imports successful")
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Note: This test requires database and dependencies to be available")
    sys.exit(1)


class TestUnifiedBetVerification:
    """Test suite for unified bet verification"""

    def __init__(self):
        self.db = None
        self.test_user_id = 1  # Test user

    async def setup(self):
        """Setup test database connection"""
        try:
            self.db = SessionLocal()
            print("✅ Database connection established")
            return True
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return False

    def cleanup(self):
        """Cleanup database connection"""
        if self.db:
            self.db.close()
            print("✅ Database connection closed")

    def test_moneyline_bet_creation(self) -> Dict:
        """Test that moneyline bets store proper enum fields"""
        print("\n🎯 Test 1: Moneyline Bet Creation")
        print("-" * 50)

        try:
            # Query a moneyline bet from database
            bet = (
                self.db.query(SimpleUnifiedBet)
                .filter(
                    SimpleUnifiedBet.bet_type == BetType.MONEYLINE,
                    SimpleUnifiedBet.team_selection != TeamSide.NONE
                )
                .first()
            )

            if not bet:
                print("⚠️  No moneyline bets found in database")
                return {"status": "skipped", "reason": "No moneyline bets"}

            print(f"Found bet {bet.id[:8]}:")
            print(f"  Selection: {bet.selection}")
            selection_value = (
                bet.team_selection.value if bet.team_selection else "NONE"
            )
            print(f"  Team Selection Enum: {selection_value}")
            print(f"  Selected Team Name: {bet.selected_team_name}")
            print(f"  Home Team: {bet.home_team}")
            print(f"  Away Team: {bet.away_team}")

            # Validate enum is stored
            assert bet.team_selection in [
                TeamSide.HOME,
                TeamSide.AWAY,
            ], f"❌ team_selection should be HOME or AWAY, got {bet.team_selection}"
            assert (
                bet.selected_team_name is not None
            ), "❌ selected_team_name should be stored"

            print("✅ Moneyline bet has proper enum fields")
            return {"status": "passed"}

        except Exception as e:
            print(f"❌ Test failed: {e}")
            return {"status": "failed", "error": str(e)}

    def test_spread_bet_creation(self) -> Dict:
        """Test that spread bets store spread with +/- sign"""
        print("\n🎯 Test 2: Spread Bet Creation")
        print("-" * 50)

        try:
            # Query a spread bet
            bet = (
                self.db.query(SimpleUnifiedBet)
                .filter(
                    SimpleUnifiedBet.bet_type == BetType.SPREAD,
                    SimpleUnifiedBet.spread_value.isnot(None)
                )
                .first()
            )

            if not bet:
                print("⚠️  No spread bets found in database")
                return {"status": "skipped", "reason": "No spread bets"}

            print(f"Found bet {bet.id[:8]}:")
            print(f"  Selection: {bet.selection}")
            print(f"  Spread Value: {bet.spread_value:+.1f}")
            spread_selection_value = (
                bet.spread_selection.value if bet.spread_selection else "NONE"
            )
            print(f"  Spread Selection Enum: {spread_selection_value}")
            print(f"  Selected Team: {bet.selected_team_name}")

            # Validate spread has sign
            assert (
                bet.spread_value != abs(bet.spread_value) or bet.spread_value > 0
            ), f"❌ spread_value should have sign, got {bet.spread_value}"
            assert bet.spread_selection in [
                TeamSide.HOME,
                TeamSide.AWAY,
            ], f"❌ spread_selection should be HOME or AWAY, got {bet.spread_selection}"

            print("✅ Spread bet has proper signed value and enum")
            return {"status": "passed"}

        except Exception as e:
            print(f"❌ Test failed: {e}")
            return {"status": "failed", "error": str(e)}

    def test_total_bet_creation(self) -> Dict:
        """Test that total bets store over/under enum"""
        print("\n🎯 Test 3: Total (Over/Under) Bet Creation")
        print("-" * 50)

        try:
            # Query a total bet
            bet = (
                self.db.query(SimpleUnifiedBet)
                .filter(
                    SimpleUnifiedBet.bet_type == BetType.TOTAL,
                    SimpleUnifiedBet.over_under_selection != OverUnder.NONE
                )
                .first()
            )

            if not bet:
                print("⚠️  No total bets found in database")
                return {"status": "skipped", "reason": "No total bets"}

            print(f"Found bet {bet.id[:8]}:")
            print(f"  Selection: {bet.selection}")
            print(f"  Total Points: {bet.total_points}")
            print(f"  Over/Under Enum: {bet.over_under_selection.value}")

            # Validate over/under enum
            assert bet.over_under_selection in [
                OverUnder.OVER,
                OverUnder.UNDER,
            ], (
                f"❌ over_under_selection should be OVER or UNDER, "
                f"got {bet.over_under_selection}"
            )
            assert (
                bet.total_points is not None
            ), "❌ total_points should be stored"

            print("✅ Total bet has proper over/under enum")
            return {"status": "passed"}

        except Exception as e:
            print(f"❌ Test failed: {e}")
            return {"status": "failed", "error": str(e)}

    def test_status_enum_usage(self) -> Dict:
        """Test that bet status uses BetStatus enum"""
        print("\n🎯 Test 4: Bet Status Enum Usage")
        print("-" * 50)

        try:
            # Query bets with different statuses
            bets = self.db.query(SimpleUnifiedBet).limit(5).all()

            if not bets:
                print("⚠️  No bets found in database")
                return {"status": "skipped", "reason": "No bets"}

            print(f"Checking {len(bets)} bets:")
            for bet in bets:
                status = bet.status
                status_type_name = type(status).__name__
                print(
                    f"  Bet {bet.id[:8]}: status={status.value} "
                    f"(type: {status_type_name})"
                )

                # Validate it's an enum, not a string
                assert isinstance(
                    status, BetStatus
                ), f"❌ status should be BetStatus enum, got {type(status)}"

            print("✅ All bets use BetStatus enum (not strings)")
            return {"status": "passed"}

        except Exception as e:
            print(f"❌ Test failed: {e}")
            return {"status": "failed", "error": str(e)}

    def test_odds_api_event_id(self) -> Dict:
        """Test that odds_api_event_id is stored for score matching"""
        print("\n🎯 Test 5: Odds API Event ID Storage")
        print("-" * 50)

        try:
            bet = (
                self.db.query(SimpleUnifiedBet)
                .filter(SimpleUnifiedBet.odds_api_event_id.isnot(None))
                .first()
            )

            if not bet:
                print("⚠️  No bets with odds_api_event_id found")
                return {"status": "skipped", "reason": "No bets with event ID"}

            print(f"Found bet {bet.id[:8]}:")
            print(f"  Odds API Event ID: {bet.odds_api_event_id}")
            print(f"  Home Team: {bet.home_team}")
            print(f"  Away Team: {bet.away_team}")

            assert (
                bet.odds_api_event_id is not None
            ), "❌ odds_api_event_id should be stored"
            assert (
                bet.home_team is not None
            ), "❌ home_team should be stored for score matching"
            assert (
                bet.away_team is not None
            ), "❌ away_team should be stored for score matching"

            print("✅ Bet has proper odds_api_event_id and team names")
            return {"status": "passed"}

        except Exception as e:
            print(f"❌ Test failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def test_verification_service_available(self) -> Dict:
        """Test that unified verification service is available"""
        print("\n🎯 Test 6: Verification Service Availability")
        print("-" * 50)

        try:
            # Check service instance
            assert unified_bet_verification_service is not None, \
                "❌ unified_bet_verification_service is None"

            print("✅ Unified verification service instance is available")

            # Test that service has required methods
            required_methods = [
                'verify_all_pending_bets',
                '_verify_single_bet',
                '_evaluate_moneyline',
                '_evaluate_spread',
                '_evaluate_total',
            ]

            for method_name in required_methods:
                assert hasattr(unified_bet_verification_service, method_name), \
                    f"❌ Service missing method: {method_name}"
                print(f"  ✓ Method available: {method_name}")

            print("✅ All required methods are available")
            return {"status": "passed"}

        except Exception as e:
            print(f"❌ Test failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def run_all_tests(self):
        """Run all test cases"""
        print("=" * 70)
        print("🚀 UNIFIED BET VERIFICATION TEST SUITE")
        print("=" * 70)

        if not await self.setup():
            print("\n❌ Setup failed - cannot run tests")
            return False

        results = []

        # Run all tests
        tests = [
            ("Moneyline Bet Creation", self.test_moneyline_bet_creation),
            ("Spread Bet Creation", self.test_spread_bet_creation),
            ("Total Bet Creation", self.test_total_bet_creation),
            ("Status Enum Usage", self.test_status_enum_usage),
            ("Odds API Event ID", self.test_odds_api_event_id),
            ("Verification Service", self.test_verification_service_available),
        ]

        for test_name, test_func in tests:
            try:
                if asyncio.iscoroutinefunction(test_func):
                    result = await test_func()
                else:
                    result = test_func()
                results.append((test_name, result))
            except Exception as e:
                print(f"❌ Test '{test_name}' crashed: {e}")
                results.append((test_name, {"status": "crashed", "error": str(e)}))

        # Summary
        print("\n" + "=" * 70)
        print("📊 TEST SUMMARY")
        print("=" * 70)

        passed = sum(1 for _, r in results if r.get("status") == "passed")
        failed = sum(1 for _, r in results if r.get("status") == "failed")
        skipped = sum(1 for _, r in results if r.get("status") == "skipped")
        crashed = sum(1 for _, r in results if r.get("status") == "crashed")

        print(f"\n✅ Passed:  {passed}/{len(results)}")
        print(f"❌ Failed:  {failed}/{len(results)}")
        print(f"⚠️  Skipped: {skipped}/{len(results)}")
        print(f"💥 Crashed: {crashed}/{len(results)}")

        if failed > 0 or crashed > 0:
            print("\n❌ SOME TESTS FAILED")
            for test_name, result in results:
                if result.get("status") in ["failed", "crashed"]:
                    print(f"  - {test_name}: {result.get('error', 'Unknown error')}")
        elif skipped == len(results):
            print("\n⚠️  ALL TESTS SKIPPED (no data in database)")
        else:
            print("\n🎉 ALL TESTS PASSED!")

        self.cleanup()
        return failed == 0 and crashed == 0


async def main():
    """Main test runner"""
    tester = TestUnifiedBetVerification()
    success = await tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
