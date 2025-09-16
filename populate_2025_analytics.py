#!/usr/bin/env python3
"""
Populate player_analytics table with realistic 2025 season data (weeks 1-3)
"""
import random
import psycopg2
from datetime import datetime, timedelta
import sys

# Database connection
DB_CONFIG = {
    'host': 'localhost',
    'database': 'sports_betting_ai',
    'user': 'sports_user',
    'password': 'sports_pass'
}

# NFL teams for opponent generation
NFL_TEAMS = [
    'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN',
    'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC', 'LV', 'LAC', 'LAR', 'MIA',
    'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SF', 'SEA', 'TB',
    'TEN', 'WSH'
]

# Position-based statistical templates
POSITION_TEMPLATES = {
    'QB': {
        'snap_percentage_range': (85, 100),
        'targets_range': (0, 2),
        'target_share_range': (0.0, 0.02),
        'carries_range': (0, 8),
        'red_zone_share_range': (0.0, 0.05),
        'ppr_points_range': (8, 35),
        'usage_tier_distribution': {'elite': 0.1, 'starter': 0.4, 'backup': 0.5}
    },
    'RB': {
        'snap_percentage_range': (25, 85),
        'targets_range': (0, 12),
        'target_share_range': (0.0, 0.20),
        'carries_range': (5, 25),
        'red_zone_share_range': (0.0, 0.60),
        'ppr_points_range': (2, 30),
        'usage_tier_distribution': {'elite': 0.15, 'starter': 0.35, 'backup': 0.5}
    },
    'WR': {
        'snap_percentage_range': (30, 95),
        'targets_range': (0, 15),
        'target_share_range': (0.0, 0.30),
        'carries_range': (0, 2),
        'red_zone_share_range': (0.0, 0.40),
        'ppr_points_range': (0, 35),
        'usage_tier_distribution': {'elite': 0.12, 'starter': 0.28, 'backup': 0.6}
    },
    'TE': {
        'snap_percentage_range': (40, 90),
        'targets_range': (0, 12),
        'target_share_range': (0.0, 0.25),
        'carries_range': (0, 1),
        'red_zone_share_range': (0.0, 0.35),
        'ppr_points_range': (0, 25),
        'usage_tier_distribution': {'elite': 0.1, 'starter': 0.3, 'backup': 0.6}
    }
}

def determine_usage_tier(position, player_id):
    """Assign usage tier based on position distribution and player_id for consistency"""
    random.seed(player_id * 42)  # Consistent tier assignment
    tier_dist = POSITION_TEMPLATES[position]['usage_tier_distribution']

    rand_val = random.random()
    if rand_val < tier_dist['elite']:
        return 'elite'
    elif rand_val < tier_dist['elite'] + tier_dist['starter']:
        return 'starter'
    else:
        return 'backup'

def calculate_tier_multipliers(tier):
    """Get stat multipliers based on usage tier"""
    multipliers = {
        'elite': {'base': 1.3, 'variance': 0.2},
        'starter': {'base': 1.0, 'variance': 0.3},
        'backup': {'base': 0.4, 'variance': 0.5}
    }
    return multipliers[tier]

def generate_realistic_stats(position, player_id, week, tier):
    """Generate realistic weekly stats for a player"""
    random.seed(player_id * week * 2025)  # Consistent but varied stats

    template = POSITION_TEMPLATES[position]
    multipliers = calculate_tier_multipliers(tier)

    # Base ranges with tier adjustments
    snap_min, snap_max = template['snap_percentage_range']
    target_min, target_max = template['targets_range']
    target_share_min, target_share_max = template['target_share_range']
    carry_min, carry_max = template['carries_range']
    rz_share_min, rz_share_max = template['red_zone_share_range']
    points_min, points_max = template['ppr_points_range']

    # Apply tier multipliers
    snap_percentage = random.uniform(
        max(10, snap_min * multipliers['base'] - 10),
        min(100, snap_max * multipliers['base'] + 5)
    )

    targets = max(0, int(random.uniform(
        target_min * multipliers['base'],
        target_max * multipliers['base']
    )))

    target_share = max(0.0, min(0.35, random.uniform(
        target_share_min * multipliers['base'],
        target_share_max * multipliers['base']
    )))

    carries = max(0, int(random.uniform(
        carry_min * multipliers['base'],
        carry_max * multipliers['base']
    )))

    red_zone_share = max(0.0, min(0.8, random.uniform(
        rz_share_min * multipliers['base'],
        rz_share_max * multipliers['base']
    )))

    # PPR points based on usage
    base_points = random.uniform(points_min, points_max) * multipliers['base']
    ppr_points = max(0, base_points + random.uniform(-5, 5))

    # Calculate dependent stats
    total_snaps = max(10, int(snap_percentage * random.uniform(60, 80)))
    offensive_snaps = int(total_snaps * random.uniform(0.85, 1.0))

    # Receiving stats
    if targets > 0:
        receptions = max(0, int(targets * random.uniform(0.5, 0.9)))
        receiving_yards = max(0, int(receptions * random.uniform(8, 18)))
        air_yards = max(0, int(targets * random.uniform(6, 15)))
    else:
        receptions = receiving_yards = air_yards = 0

    # Rushing stats for RBs and some others
    if carries > 0:
        rushing_yards = max(0, int(carries * random.uniform(3.5, 6.2)))
    else:
        rushing_yards = 0

    # Red zone touches
    red_zone_targets = max(0, int(targets * random.uniform(0.1, 0.3))) if targets > 0 else 0
    red_zone_carries = max(0, int(carries * random.uniform(0.15, 0.4))) if carries > 0 else 0
    red_zone_touches = red_zone_targets + red_zone_carries

    # Efficiency metrics
    points_per_snap = round(ppr_points / total_snaps, 3) if total_snaps > 0 else 0
    points_per_target = round(ppr_points / targets, 3) if targets > 0 else 0
    points_per_touch = round(ppr_points / (targets + carries), 3) if (targets + carries) > 0 else 0

    # Generate game context
    opponent = random.choice(NFL_TEAMS)
    game_scripts = ['positive', 'neutral', 'negative']
    game_script = random.choice(game_scripts)

    # Week-specific date (approximate 2025 season start)
    base_date = datetime(2025, 9, 8)  # Week 1 approximate start
    game_date = base_date + timedelta(days=(week-1)*7 + random.randint(0, 3))

    return {
        'total_snaps': total_snaps,
        'offensive_snaps': offensive_snaps,
        'special_teams_snaps': max(0, total_snaps - offensive_snaps),
        'snap_percentage': round(snap_percentage, 1),
        'targets': targets,
        'target_share': round(target_share, 4),
        'carries': carries,
        'red_zone_share': round(red_zone_share, 4),
        'red_zone_targets': red_zone_targets,
        'red_zone_carries': red_zone_carries,
        'red_zone_touches': red_zone_touches,
        'receptions': receptions,
        'receiving_yards': receiving_yards,
        'rushing_yards': rushing_yards,
        'air_yards': air_yards,
        'ppr_points': round(ppr_points, 1),
        'points_per_snap': points_per_snap,
        'points_per_target': points_per_target,
        'points_per_touch': points_per_touch,
        'opponent': opponent,
        'game_script': game_script,
        'game_date': game_date
    }

def populate_2025_data():
    """Main function to populate 2025 analytics data"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        print("Connected to database successfully")

        # Get all fantasy players
        cur.execute("""
            SELECT id, name, position, team
            FROM fantasy_players
            WHERE position IN ('QB', 'RB', 'WR', 'TE')
            ORDER BY id
        """)
        players = cur.fetchall()

        print(f"Found {len(players)} players to populate")

        # Clear existing 2025 data
        print("Clearing existing 2025 data...")
        cur.execute("DELETE FROM player_analytics WHERE season = 2025")
        conn.commit()

        total_records = 0

        # Generate data for weeks 1-3 of 2025
        for week in [1, 2, 3]:
            print(f"Generating Week {week} data...")

            for player_id, name, position, team in players:
                tier = determine_usage_tier(position, player_id)
                stats = generate_realistic_stats(position, player_id, week, tier)

                # Insert the record
                insert_query = """
                    INSERT INTO player_analytics (
                        player_id, week, season, game_date, opponent,
                        total_snaps, offensive_snaps, special_teams_snaps, snap_percentage,
                        targets, target_share, carries, red_zone_share,
                        red_zone_targets, red_zone_carries, red_zone_touches,
                        receptions, receiving_yards, rushing_yards, air_yards,
                        ppr_points, points_per_snap, points_per_target, points_per_touch,
                        game_script, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """

                cur.execute(insert_query, (
                    player_id, week, 2025, stats['game_date'], stats['opponent'],
                    stats['total_snaps'], stats['offensive_snaps'], stats['special_teams_snaps'],
                    stats['snap_percentage'], stats['targets'], stats['target_share'],
                    stats['carries'], stats['red_zone_share'], stats['red_zone_targets'],
                    stats['red_zone_carries'], stats['red_zone_touches'], stats['receptions'],
                    stats['receiving_yards'], stats['rushing_yards'], stats['air_yards'],
                    stats['ppr_points'], stats['points_per_snap'], stats['points_per_target'],
                    stats['points_per_touch'], stats['game_script'], datetime.now()
                ))

                total_records += 1

                if total_records % 100 == 0:
                    print(f"  Inserted {total_records} records...")
                    conn.commit()

        # Final commit
        conn.commit()
        print(f"Successfully populated {total_records} records for 2025 season!")

        # Verify the data
        cur.execute("""
            SELECT COUNT(*) as total, COUNT(DISTINCT player_id) as players,
                   AVG(target_share) as avg_target_share, AVG(red_zone_share) as avg_rz_share
            FROM player_analytics WHERE season = 2025
        """)
        verification = cur.fetchone()
        print(f"Verification - Total: {verification[0]}, Players: {verification[1]}")
        print(f"Avg Target Share: {verification[2]:.3f}, Avg RZ Share: {verification[3]:.3f}")

        cur.close()
        conn.close()

    except Exception as e:
        print(f"Error: {e}")
        return False

    return True

if __name__ == "__main__":
    print("Starting 2025 season data population...")
    success = populate_2025_data()

    if success:
        print("✅ Data population completed successfully!")
        sys.exit(0)
    else:
        print("❌ Data population failed!")
        sys.exit(1)