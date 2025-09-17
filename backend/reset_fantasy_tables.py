#!/usr/bin/env python3
"""
Reset and rebuild fantasy tables with simplified structure
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import get_db, engine
from app.models.database_models import User
from sqlalchemy import text
import requests


def reset_fantasy_tables():
    """Drop existing fantasy tables and rebuild with simplified structure"""
    db = next(get_db())

    try:
        print("🗑️  Dropping existing fantasy tables...")

        # Drop tables in reverse dependency order
        tables_to_drop = [
            "trade_proposals",
            "roster_spots",
            "players",
            "teams",
            "leagues",
            "fantasy_roster_spots",
            "fantasy_players",
            "fantasy_teams",
            "fantasy_leagues",
            "fantasy_users",
            "player_values",
            "team_needs_analysis",
        ]

        for table in tables_to_drop:
            try:
                db.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                print(f"  ✓ Dropped {table}")
            except Exception as e:
                print(f"  ⚠️  Could not drop {table}: {e}")

        db.commit()
        print("\n🏗️  Creating new simplified tables...")

        # Create simplified tables
        db.execute(
            text(
                """
        CREATE TABLE leagues (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            platform VARCHAR(50) DEFAULT 'sleeper',
            platform_league_id VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            season INTEGER NOT NULL,
            status VARCHAR(50) DEFAULT 'in_season',
            scoring_type VARCHAR(50) DEFAULT 'half_ppr',
            total_teams INTEGER DEFAULT 12,
            roster_positions JSON,
            scoring_settings JSON,
            last_synced TIMESTAMP DEFAULT NOW(),
            sync_enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, platform_league_id, season)
        )
        """
            )
        )
        print("  ✓ Created leagues table")

        db.execute(
            text(
                """
        CREATE TABLE teams (
            id SERIAL PRIMARY KEY,
            league_id INTEGER NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
            platform_team_id VARCHAR(255) NOT NULL,
            platform_owner_id VARCHAR(255),
            name VARCHAR(255) NOT NULL,
            owner_name VARCHAR(255),
            is_user_team BOOLEAN DEFAULT FALSE,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            ties INTEGER DEFAULT 0,
            points_for FLOAT DEFAULT 0.0,
            points_against FLOAT DEFAULT 0.0,
            waiver_position INTEGER,
            playoff_seed INTEGER,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
            )
        )
        print("  ✓ Created teams table")

        db.execute(
            text(
                """
        CREATE TABLE players (
            id SERIAL PRIMARY KEY,
            platform VARCHAR(50) DEFAULT 'sleeper',
            platform_player_id VARCHAR(255) NOT NULL UNIQUE,
            name VARCHAR(255) NOT NULL,
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            position VARCHAR(10) NOT NULL,
            team VARCHAR(10),
            age INTEGER,
            height VARCHAR(10),
            weight VARCHAR(10),
            college VARCHAR(255),
            years_exp INTEGER,
            status VARCHAR(50) DEFAULT 'Active',
            injury_status VARCHAR(50),
            espn_id VARCHAR(50),
            yahoo_id VARCHAR(50),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
            )
        )
        print("  ✓ Created players table")

        db.execute(
            text(
                """
        CREATE TABLE roster_spots (
            id SERIAL PRIMARY KEY,
            team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            player_id INTEGER NOT NULL REFERENCES players(id),
            position VARCHAR(10) NOT NULL,
            week INTEGER DEFAULT 1,
            is_starter BOOLEAN DEFAULT FALSE,
            points_scored FLOAT DEFAULT 0.0,
            projected_points FLOAT DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(team_id, player_id, week)
        )
        """
            )
        )
        print("  ✓ Created roster_spots table")

        # Add indexes for performance
        db.execute(text("CREATE INDEX idx_leagues_user_id ON leagues(user_id)"))
        db.execute(text("CREATE INDEX idx_leagues_season ON leagues(season)"))
        db.execute(text("CREATE INDEX idx_teams_league_id ON teams(league_id)"))
        db.execute(text("CREATE INDEX idx_teams_is_user_team ON teams(is_user_team)"))
        db.execute(
            text("CREATE INDEX idx_players_platform_id ON players(platform_player_id)")
        )
        db.execute(text("CREATE INDEX idx_players_position ON players(position)"))
        db.execute(
            text("CREATE INDEX idx_roster_spots_team_id ON roster_spots(team_id)")
        )
        print("  ✓ Created indexes")

        # Add sleeper_user_id to users table if it doesn't exist
        try:
            db.execute(
                text("ALTER TABLE users ADD COLUMN sleeper_user_id VARCHAR(255)")
            )
            db.execute(
                text("ALTER TABLE users ADD COLUMN sleeper_username VARCHAR(255)")
            )
            print("  ✓ Added Sleeper fields to users table")
        except Exception as e:
            print(f"  ℹ️  Sleeper fields might already exist: {e}")

        db.commit()
        print("\n✅ Tables created successfully!")

        return True

    except Exception as e:
        print(f"❌ Error resetting tables: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()


def populate_user_sleeper_data():
    """Update existing user with Sleeper data"""
    db = next(get_db())

    try:
        # Update the main user (byetra@gmail.com) with Sleeper info
        user = db.query(User).filter(User.email == "byetra@gmail.com").first()
        if user:
            user.sleeper_user_id = "644638080736759808"
            user.sleeper_username = "byetra"  # You can update this with actual username
            db.commit()
            print(f"✅ Updated user {user.email} with Sleeper data")
            return user.id
        else:
            print("❌ User byetra@gmail.com not found")
            return None

    except Exception as e:
        print(f"❌ Error updating user: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def populate_simplified_data(user_id: int):
    """Populate the simplified tables with current season data"""
    # Use a fresh connection for data insertion
    from sqlalchemy import create_engine
    from app.core.config import settings

    engine = create_engine(settings.DATABASE_URL)
    db = engine.connect()

    try:
        print("📊 Populating simplified tables with 2025 data...")

        # Start transaction
        trans = db.begin()

        # Create 2025 league
        db.execute(
            text(
                """
        INSERT INTO leagues (user_id, platform_league_id, name, season, total_teams)
        VALUES (:user_id, '1257417114529054720', 'Mike''s Hard Fantasy Football', 2025, 12)
        """
            ),
            {"user_id": user_id},
        )

        league_result = db.execute(
            text("SELECT id FROM leagues WHERE user_id = :user_id AND season = 2025"),
            {"user_id": user_id},
        )
        league_id = league_result.fetchone()[0]
        print(f"  ✓ Created league {league_id}")

        # Create your team
        db.execute(
            text(
                """
        INSERT INTO teams (league_id, platform_team_id, platform_owner_id, name, owner_name, is_user_team, wins, losses)
        VALUES (:league_id, '1', '644638080736759808', 'Sir Spanks-A-LOT', 'byetra', TRUE, 8, 6)
        """
            ),
            {"league_id": league_id},
        )

        team_result = db.execute(
            text(
                "SELECT id FROM teams WHERE league_id = :league_id AND is_user_team = TRUE"
            ),
            {"league_id": league_id},
        )
        team_id = team_result.fetchone()[0]
        print(f"  ✓ Created user team {team_id}")

        # Add your current 2025 roster
        current_roster = [
            {
                "name": "Jayden Daniels",
                "platform_id": "11566",
                "position": "QB",
                "team": "WAS",
                "is_starter": True,
            },
            {
                "name": "Bijan Robinson",
                "platform_id": "11651",
                "position": "RB",
                "team": "ATL",
                "is_starter": True,
            },
            {
                "name": "Isaac Guerendo",
                "platform_id": "2216",
                "position": "RB",
                "team": "SF",
                "is_starter": True,
            },
            {
                "name": "Deebo Samuel",
                "platform_id": "3163",
                "position": "WR",
                "team": "WAS",
                "is_starter": True,
            },
            {
                "name": "Mike Evans",
                "platform_id": "4018",
                "position": "WR",
                "team": "TB",
                "is_starter": True,
            },
            {
                "name": "Evan Engram",
                "platform_id": "4066",
                "position": "TE",
                "team": "DEN",
                "is_starter": True,
            },
            {
                "name": "Joe Mixon",
                "platform_id": "5872",
                "position": "RB",
                "team": "HOU",
                "is_starter": True,
            },
            {
                "name": "Minnesota Vikings",
                "platform_id": "MIN",
                "position": "DEF",
                "team": "MIN",
                "is_starter": True,
            },
            {
                "name": "Jared Goff",
                "platform_id": "210",
                "position": "QB",
                "team": "DET",
                "is_starter": False,
            },
            {
                "name": "C.J. Stroud",
                "platform_id": "324",
                "position": "QB",
                "team": "HOU",
                "is_starter": False,
            },
            {
                "name": "Chuba Hubbard",
                "platform_id": "310",
                "position": "RB",
                "team": "CAR",
                "is_starter": False,
            },
            {
                "name": "Jaylen Waddle",
                "platform_id": "44",
                "position": "WR",
                "team": "MIA",
                "is_starter": False,
            },
            {
                "name": "Chris Olave",
                "platform_id": "294",
                "position": "WR",
                "team": "NO",
                "is_starter": False,
            },
            {
                "name": "Tank Dell",
                "platform_id": "327",
                "position": "WR",
                "team": "HOU",
                "is_starter": False,
            },
        ]

        for player_data in current_roster:
            # Insert player
            db.execute(
                text(
                    """
            INSERT INTO players (platform_player_id, name, position, team) 
            VALUES (:platform_id, :name, :position, :team)
            ON CONFLICT (platform_player_id) DO NOTHING
            """
                ),
                player_data,
            )

            # Get player ID
            player_result = db.execute(
                text("SELECT id FROM players WHERE platform_player_id = :platform_id"),
                {"platform_id": player_data["platform_id"]},
            )
            player_row = player_result.fetchone()
            if player_row:
                player_id = player_row[0]

                # Insert roster spot
                db.execute(
                    text(
                        """
                INSERT INTO roster_spots (team_id, player_id, position, week, is_starter)
                VALUES (:team_id, :player_id, :position, 8, :is_starter)
                """
                    ),
                    {
                        "team_id": team_id,
                        "player_id": player_id,
                        "position": player_data["position"],
                        "is_starter": player_data["is_starter"],
                    },
                )

        # Commit transaction
        trans.commit()
        print(f"  ✅ Added {len(current_roster)} players to roster")

        # Show summary
        roster_count = db.execute(
            text("SELECT COUNT(*) FROM roster_spots WHERE team_id = :team_id"),
            {"team_id": team_id},
        ).fetchone()[0]
        print(f"\n🎉 Setup complete!")
        print(f"   League ID: {league_id}")
        print(f"   Team ID: {team_id}")
        print(f"   Roster size: {roster_count} players")

        return {"league_id": league_id, "team_id": team_id}

    except Exception as e:
        print(f"❌ Error populating data: {e}")
        import traceback

        traceback.print_exc()
        return None
    finally:
        db.close()


if __name__ == "__main__":
    print("🔄 Resetting fantasy database structure...")

    # Step 1: Reset tables
    if not reset_fantasy_tables():
        exit(1)

    # Step 2: Update user with Sleeper data
    user_id = populate_user_sleeper_data()
    if not user_id:
        exit(1)

    # Step 3: Populate with current data
    result = populate_simplified_data(user_id)
    if not result:
        exit(1)

    print("\n🚀 Fantasy database reset complete!")
    print(f"   Your league: ID {result['league_id']}")
    print(f"   Your team: ID {result['team_id']}")
    print("\nYou can now use the simplified structure:")
    print("   - Single leagues table (no FantasyLeague/FantasyUser complexity)")
    print("   - Direct user->league relationship")
    print("   - Clear team ownership with is_user_team flag")
    print("   - Simple player->roster_spot relationships")
