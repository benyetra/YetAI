#!/usr/bin/env python3
"""
Simple Enhanced Bet Migration - Step by step approach

This script creates the enhanced table and migrates data in smaller, controlled steps.
"""

import asyncio
import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import engine, SessionLocal
from app.models.simple_unified_bet_model import SimpleUnifiedBet
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_enhanced_table():
    """Create enhanced table structure"""
    logger.info("🏗️ Creating enhanced unified bets table...")

    try:
        # Create the table
        SimpleUnifiedBet.__table__.create(engine, checkfirst=True)
        logger.info("✅ Enhanced table created successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Table creation failed: {e}")
        return False


async def migrate_data_step_by_step():
    """Migrate data in controlled steps"""

    logger.info("📊 Starting step-by-step data migration...")

    # Step 1: Create table
    if not await create_enhanced_table():
        return False

    # Step 2: Test basic insertion
    logger.info("🧪 Testing basic insertion...")
    db = SessionLocal()
    try:
        # Create a simple test record
        test_bet = SimpleUnifiedBet(
            id="test-123",
            user_id=1,
            odds_api_event_id="test-event",
            bet_type="MONEYLINE",
            amount=100.0,
            odds=-110.0,
            potential_win=90.91,
            selection="Test Selection",
            home_team="Team A",
            away_team="Team B",
            sport="test_sport",
            commence_time=datetime.utcnow(),
            source="STRAIGHT",
            bookmaker="fanduel"
        )

        db.add(test_bet)
        db.commit()

        # Verify insertion
        count = db.query(SimpleUnifiedBet).count()
        logger.info(f"✅ Test insertion successful. Table has {count} records")

        # Clean up test record
        db.query(SimpleUnifiedBet).filter(SimpleUnifiedBet.id == "test-123").delete()
        db.commit()

        return True

    except Exception as e:
        logger.error(f"❌ Test insertion failed: {e}")
        db.rollback()
        return False
    finally:
        db.close()


async def check_current_data():
    """Check what data we have"""
    logger.info("🔍 Checking current data...")

    db = SessionLocal()
    try:
        # Check counts
        straight_bets = db.execute(text("SELECT COUNT(*) FROM bets WHERE parlay_id IS NULL")).scalar()
        parlay_bets = db.execute(text("SELECT COUNT(*) FROM parlay_bets")).scalar()
        parlay_legs = db.execute(text("SELECT COUNT(*) FROM bets WHERE parlay_id IS NOT NULL")).scalar()
        live_bets = db.execute(text("SELECT COUNT(*) FROM live_bets")).scalar()

        logger.info(f"📊 Data counts:")
        logger.info(f"   Straight bets: {straight_bets}")
        logger.info(f"   Parlay parents: {parlay_bets}")
        logger.info(f"   Parlay legs: {parlay_legs}")
        logger.info(f"   Live bets: {live_bets}")

        # Check a sample bet
        sample_bet = db.execute(text("SELECT * FROM bets LIMIT 1")).first()
        if sample_bet:
            logger.info(f"📝 Sample bet: {dict(sample_bet._mapping)}")

    finally:
        db.close()


async def main():
    """Main function"""
    logger.info("🚀 Simple Enhanced Migration")
    logger.info("=" * 50)

    # Step 1: Check current data
    await check_current_data()

    # Step 2: Test table creation and basic operations
    success = await migrate_data_step_by_step()

    if success:
        logger.info("✅ Enhanced table ready for data migration")
        logger.info("💡 You can now run the full migration or migrate data manually")
    else:
        logger.error("❌ Setup failed")

    return success


if __name__ == "__main__":
    asyncio.run(main())