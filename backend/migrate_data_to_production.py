#!/usr/bin/env python3
"""
Migration script to populate production database with fantasy players and analytics data.
This script should be run in the Railway environment where DATABASE_URL is available.
"""

import os
import psycopg2
from psycopg2.extras import execute_values
import json
from typing import List, Dict

def get_db_connection():
    """Get database connection using Railway DATABASE_URL"""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not found")

    return psycopg2.connect(database_url)

def load_sql_file(filepath: str) -> str:
    """Load SQL file contents"""
    with open(filepath, 'r') as f:
        return f.read()

def execute_sql_file(cursor, sql_content: str, description: str):
    """Execute SQL file contents"""
    print(f"Executing {description}...")

    # Split by individual INSERT statements
    statements = [stmt.strip() for stmt in sql_content.split(';\n') if stmt.strip()]

    executed = 0
    for statement in statements:
        if statement.startswith('INSERT'):
            try:
                cursor.execute(statement + ';')
                executed += 1
                if executed % 100 == 0:
                    print(f"  Executed {executed} INSERT statements...")
            except Exception as e:
                print(f"Error executing statement: {e}")
                print(f"Statement: {statement[:100]}...")
                continue

    print(f"Successfully executed {executed} INSERT statements for {description}")

def main():
    print("Starting production database migration...")

    try:
        # Connect to database
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check current state
        cursor.execute("SELECT COUNT(*) FROM player_analytics;")
        analytics_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM fantasy_players;")
        players_count = cursor.fetchone()[0]

        print(f"Current state - Players: {players_count}, Analytics: {analytics_count}")

        if players_count == 0:
            # Load and execute fantasy players data
            print("Loading fantasy players data...")
            players_sql = load_sql_file('fantasy_players_data.sql')
            execute_sql_file(cursor, players_sql, "fantasy players data")
            conn.commit()

            # Verify players imported
            cursor.execute("SELECT COUNT(*) FROM fantasy_players;")
            new_players_count = cursor.fetchone()[0]
            print(f"Fantasy players imported: {new_players_count}")
        else:
            print("Fantasy players already exist, skipping...")

        if analytics_count == 0:
            # Load and execute analytics data
            print("Loading player analytics data...")
            analytics_sql = load_sql_file('player_analytics_data.sql')
            execute_sql_file(cursor, analytics_sql, "player analytics data")
            conn.commit()

            # Verify analytics imported
            cursor.execute("SELECT COUNT(*) FROM player_analytics;")
            new_analytics_count = cursor.fetchone()[0]
            print(f"Player analytics imported: {new_analytics_count}")
        else:
            print("Player analytics already exist, skipping...")

        # Final verification
        cursor.execute("SELECT COUNT(*) FROM fantasy_players;")
        final_players = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM player_analytics;")
        final_analytics = cursor.fetchone()[0]

        cursor.execute("SELECT DISTINCT season FROM player_analytics ORDER BY season;")
        seasons = [row[0] for row in cursor.fetchall()]

        print(f"\nMigration complete!")
        print(f"Final counts - Players: {final_players}, Analytics: {final_analytics}")
        print(f"Available seasons: {seasons}")

        # Test a sample query
        cursor.execute("""
            SELECT fp.name, fp.position, fp.team, COUNT(pa.id) as analytics_records
            FROM fantasy_players fp
            LEFT JOIN player_analytics pa ON fp.platform_player_id::text = pa.player_id::text
            GROUP BY fp.id, fp.name, fp.position, fp.team
            HAVING COUNT(pa.id) > 0
            ORDER BY COUNT(pa.id) DESC
            LIMIT 5;
        """)
        sample_data = cursor.fetchall()

        print(f"\nSample players with analytics data:")
        for row in sample_data:
            print(f"  {row[0]} ({row[1]}, {row[2]}) - {row[3]} records")

        cursor.close()
        conn.close()

        print("\nDatabase migration completed successfully!")

    except Exception as e:
        print(f"Migration failed: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())