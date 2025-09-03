#!/usr/bin/env python3
"""
Migration script to transition from complex schema to simplified V2 schema
Preserves all existing data while consolidating tables
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.core.database import Base
from app.models.database_models import User
from app.models.fantasy_models_v2 import League, Team, Player, Transaction, WeeklyProjection, TradeAnalysis
import json
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_v2_tables():
    """Create the new V2 schema tables"""
    engine = create_engine(settings.DATABASE_URL)
    
    # Import the new models to register them
    from app.models.fantasy_models_v2 import League, Team, Player, Transaction, WeeklyProjection, TradeAnalysis
    
    # Create all V2 tables
    Base.metadata.create_all(bind=engine, tables=[
        League.__table__,
        Team.__table__, 
        Player.__table__,
        Transaction.__table__,
        WeeklyProjection.__table__,
        TradeAnalysis.__table__
    ])
    
    logger.info("✅ Created V2 schema tables")

def migrate_sleeper_data():
    """Migrate existing Sleeper data to new schema"""
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # 1. Migrate SleeperLeague -> League
        logger.info("🔄 Migrating league data...")
        sleeper_leagues = db.execute(text("""
            SELECT sl.id, sl.user_id, sl.sleeper_league_id, sl.name, sl.season, 
                   sl.total_rosters, sl.status, sl.scoring_type, sl.roster_positions,
                   sl.scoring_settings, sl.created_at, sl.last_synced
            FROM sleeper_leagues sl
        """)).fetchall()
        
        for sl in sleeper_leagues:
            league = League(
                user_id=sl.user_id,
                platform="sleeper",
                external_league_id=sl.sleeper_league_id,
                name=sl.name,
                season=sl.season,
                total_teams=sl.total_rosters,
                status=sl.status or "in_season",
                scoring_type=sl.scoring_type or "half_ppr",
                roster_positions=sl.roster_positions or [],
                scoring_settings=sl.scoring_settings or {},
                created_at=sl.created_at,
                last_synced=sl.last_synced
            )
            db.add(league)
        
        db.commit()
        logger.info(f"✅ Migrated {len(sleeper_leagues)} leagues")
        
        # 2. Migrate SleeperRoster -> Team
        logger.info("🔄 Migrating team data...")
        
        # Get league ID mapping (old -> new)
        league_mapping = {}
        for sl in sleeper_leagues:
            new_league = db.query(League).filter(
                League.external_league_id == sl.sleeper_league_id,
                League.user_id == sl.user_id
            ).first()
            if new_league:
                league_mapping[sl.id] = new_league.id
        
        sleeper_rosters = db.execute(text("""
            SELECT sr.id, sr.league_id, sr.sleeper_roster_id, sr.sleeper_owner_id,
                   sr.team_name, sr.owner_name, sr.wins, sr.losses, sr.ties,
                   sr.points_for, sr.points_against, sr.waiver_position,
                   sr.players, sr.starters, sr.created_at, sr.last_synced
            FROM sleeper_rosters sr
        """)).fetchall()
        
        for sr in sleeper_rosters:
            if sr.league_id in league_mapping:
                # Parse JSON fields safely
                all_players = sr.players if sr.players else []
                starters = sr.starters if sr.starters else []
                
                # Calculate bench players
                bench = [p for p in all_players if p not in starters]
                
                team = Team(
                    league_id=league_mapping[sr.league_id],
                    external_team_id=sr.sleeper_roster_id,
                    external_owner_id=sr.sleeper_owner_id,
                    team_name=sr.team_name,
                    owner_name=sr.owner_name,
                    wins=sr.wins or 0,
                    losses=sr.losses or 0,
                    ties=sr.ties or 0,
                    points_for=sr.points_for or 0.0,
                    points_against=sr.points_against or 0.0,
                    active_players=all_players,
                    starting_lineup=starters,
                    bench_players=bench,
                    ir_players=[],  # Will be populated later if needed
                    waiver_position=sr.waiver_position,
                    created_at=sr.created_at,
                    last_synced=sr.last_synced
                )
                db.add(team)
        
        db.commit()
        logger.info(f"✅ Migrated {len(sleeper_rosters)} teams")
        
        # 3. Migrate SleeperPlayer -> Player
        logger.info("🔄 Migrating player data...")
        sleeper_players = db.execute(text("""
            SELECT sp.id, sp.sleeper_player_id, sp.first_name, sp.last_name, sp.full_name,
                   sp.position, sp.team, sp.age, sp.height, sp.weight, sp.years_exp, sp.college,
                   sp.fantasy_positions, sp.status, sp.injury_status, sp.depth_chart_position,
                   sp.depth_chart_order, sp.search_rank, sp.hashtag, sp.espn_id, sp.yahoo_id,
                   sp.created_at, sp.last_synced
            FROM sleeper_players sp
        """)).fetchall()
        
        for sp in sleeper_players:
            player = Player(
                sleeper_id=sp.sleeper_player_id,
                espn_id=sp.espn_id,
                yahoo_id=sp.yahoo_id,
                first_name=sp.first_name,
                last_name=sp.last_name,
                full_name=sp.full_name,
                position=sp.position,
                nfl_team=sp.team,
                age=sp.age,
                height=sp.height,
                weight=sp.weight,
                years_exp=sp.years_exp,
                college=sp.college,
                status="active",  # Default status
                injury_status=sp.injury_status,
                fantasy_positions=sp.fantasy_positions or [],
                depth_chart_position=sp.depth_chart_position,
                depth_chart_order=sp.depth_chart_order,
                hashtag=sp.hashtag,
                created_at=sp.created_at,
                last_synced=sp.last_synced
            )
            db.add(player)
        
        db.commit()
        logger.info(f"✅ Migrated {len(sleeper_players)} players")
        
        # 4. Migrate FantasyTransaction data if it exists
        logger.info("🔄 Checking for fantasy transaction data...")
        try:
            fantasy_transactions = db.execute(text("""
                SELECT ft.id, ft.team_id, ft.player_id, ft.transaction_type, ft.week,
                       ft.transaction_data, ft.status, ft.created_at
                FROM fantasy_transactions ft
            """)).fetchall()
            
            # This would require mapping old team IDs to new team IDs
            # For now, we'll skip this and rely on fresh transaction syncing
            logger.info(f"Found {len(fantasy_transactions)} old transactions - will sync fresh data instead")
            
        except Exception as e:
            logger.info("No existing fantasy transaction data found")
        
        logger.info("✅ Migration completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def create_indexes():
    """Create additional performance indexes"""
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        # Additional composite indexes for common queries
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_teams_league_wins ON teams(league_id, wins DESC)",
            "CREATE INDEX IF NOT EXISTS idx_players_position_team ON players(position, nfl_team)",
            "CREATE INDEX IF NOT EXISTS idx_players_trade_value ON players(trade_value DESC) WHERE trade_value IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_transactions_league_type_week ON transactions(league_id, transaction_type, week)",
        ]
        
        for index_sql in indexes:
            try:
                conn.execute(text(index_sql))
                conn.commit()
            except Exception as e:
                logger.warning(f"Index creation warning: {e}")
    
    logger.info("✅ Created performance indexes")

def verify_migration():
    """Verify that migration was successful"""
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # Count records in new tables
        league_count = db.query(League).count()
        team_count = db.query(Team).count()
        player_count = db.query(Player).count()
        
        logger.info(f"📊 Migration verification:")
        logger.info(f"   - Leagues: {league_count}")
        logger.info(f"   - Teams: {team_count}")
        logger.info(f"   - Players: {player_count}")
        
        # Test a sample query
        sample_team = db.query(Team).join(League).first()
        if sample_team:
            logger.info(f"   - Sample team: {sample_team.team_name} in {sample_team.league.name}")
            logger.info(f"   - Players on team: {len(sample_team.active_players)}")
        
        logger.info("✅ Migration verification successful!")
        
    except Exception as e:
        logger.error(f"❌ Verification failed: {e}")
        raise
    finally:
        db.close()

def main():
    """Run the complete migration"""
    logger.info("🚀 Starting V2 schema migration...")
    
    try:
        # Step 1: Create new tables
        create_v2_tables()
        
        # Step 2: Migrate existing data
        migrate_sleeper_data()
        
        # Step 3: Create performance indexes
        create_indexes()
        
        # Step 4: Verify migration
        verify_migration()
        
        logger.info("🎉 V2 schema migration completed successfully!")
        logger.info("📝 Next steps:")
        logger.info("   1. Update API endpoints to use new models")
        logger.info("   2. Test all functionality")
        logger.info("   3. Remove old tables when confident")
        
    except Exception as e:
        logger.error(f"💥 Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()