#!/usr/bin/env python3
"""
Test analytics calculations with new 2025 data
"""
import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.services.player_analytics_service import PlayerAnalyticsService

# Database setup
DATABASE_URL = "postgresql://sports_user:sports_pass@localhost/sports_betting_ai"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

async def test_nick_chubb_analytics():
    """Test Nick Chubb's analytics to verify percentage calculations"""
    db = SessionLocal()

    try:
        analytics_service = PlayerAnalyticsService(db)

        print("Testing Nick Chubb (player_id=88) analytics...")

        # Test the analytics service with 2024 real data
        analytics = await analytics_service.get_player_analytics(88, season=2024)

        print(f"Found {len(analytics)} analytics records")

        if analytics:
            print("\nWeek-by-week data:")
            total_target_share = 0
            total_rz_share = 0

            for week_data in analytics:
                target_pct = week_data['target_share'] * 100 if week_data['target_share'] else 0
                rz_pct = week_data['red_zone_share'] * 100 if week_data['red_zone_share'] else 0
                snap_pct = week_data['snap_percentage']

                print(f"Week {week_data['week']}: Target Share: {target_pct:.1f}%, RZ Share: {rz_pct:.1f}%, Snap: {snap_pct:.1f}%")

                total_target_share += week_data['target_share'] or 0
                total_rz_share += week_data['red_zone_share'] or 0

            # Test efficiency calculations with 2024 data
            efficiency = await analytics_service.calculate_efficiency_metrics(88, list(range(1, 18)), 2024)
            print(f"\nEfficiency metrics: {efficiency}")

            # Test usage trends
            trends = await analytics_service.calculate_usage_trends(88, list(range(1, 18)), 2024)
            print(f"\nUsage trends: {trends}")

            # Manual average calculation
            avg_target_share = (total_target_share / len(analytics)) * 100
            avg_rz_share = (total_rz_share / len(analytics)) * 100

            print(f"\nManual averages:")
            print(f"Average Target Share: {avg_target_share:.1f}%")
            print(f"Average RZ Share: {avg_rz_share:.1f}%")

        else:
            print("No analytics data found!")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        db.close()

async def test_top_wr_analytics():
    """Test a top WR's analytics"""
    db = SessionLocal()

    try:
        # Find Amon-Ra St. Brown or another top WR
        result = db.execute(text("SELECT id, name FROM fantasy_players WHERE name LIKE '%St. Brown%' AND position = 'WR' LIMIT 1"))
        player = result.fetchone()

        if player:
            player_id, name = player
            print(f"\nTesting {name} (player_id={player_id}) analytics...")

            analytics_service = PlayerAnalyticsService(db)
            analytics = await analytics_service.get_player_analytics(player_id, season=2024)

            if analytics:
                total_target_share = sum(w['target_share'] or 0 for w in analytics)
                total_rz_share = sum(w['red_zone_share'] or 0 for w in analytics)

                avg_target_share = (total_target_share / len(analytics)) * 100
                avg_rz_share = (total_rz_share / len(analytics)) * 100

                print(f"WR Analytics - Target Share: {avg_target_share:.1f}%, RZ Share: {avg_rz_share:.1f}%")

                # This should be much higher than Nick Chubb's target share
                if avg_target_share > 15:
                    print("✅ WR target share looks realistic (>15%)")
                else:
                    print("❌ WR target share seems low")

    except Exception as e:
        print(f"Error testing WR: {e}")

    finally:
        db.close()

async def test_historical_coverage():
    """Test analytics across all historical seasons"""
    db = SessionLocal()

    try:
        print("\n=== Testing Historical Data Coverage ===")

        # Test data availability across seasons
        for season in [2021, 2022, 2023, 2024, 2025]:
            result = db.execute(text("SELECT COUNT(DISTINCT player_id) FROM player_analytics WHERE season = :season"), {"season": season})
            player_count = result.fetchone()[0]
            print(f"{season}: {player_count} players with analytics data")

        # Test a few sample players across multiple seasons
        test_players = [
            (88, "Nick Chubb"),
            (191, "Amon-Ra St. Brown"),
            (7, "Josh Allen")  # QB test
        ]

        for player_id, name in test_players:
            analytics_service = PlayerAnalyticsService(db)

            print(f"\n=== {name} Multi-Season Analytics ===")
            for season in [2022, 2023, 2024]:
                try:
                    analytics = await analytics_service.get_player_analytics(player_id, season=season)
                    if analytics:
                        avg_target_share = sum(w['target_share'] or 0 for w in analytics) / len(analytics) * 100
                        avg_rz_share = sum(w['red_zone_share'] or 0 for w in analytics) / len(analytics) * 100
                        print(f"  {season}: {len(analytics)} weeks, {avg_target_share:.1f}% target share, {avg_rz_share:.1f}% RZ share")
                    else:
                        print(f"  {season}: No data available")
                except Exception as e:
                    print(f"  {season}: Error - {e}")

    except Exception as e:
        print(f"Error testing historical coverage: {e}")
    finally:
        db.close()

async def main():
    print("Testing analytics calculations with complete historical data...")
    await test_nick_chubb_analytics()
    await test_top_wr_analytics()
    await test_historical_coverage()

if __name__ == "__main__":
    asyncio.run(main())