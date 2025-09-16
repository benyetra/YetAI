#!/usr/bin/env python3
"""
Fetch real NFL player analytics from ESPN API for 2025 season
"""
import asyncio
import aiohttp
import psycopg2
from datetime import datetime
import json
import sys
from typing import Dict, List, Optional

# Database connection
DB_CONFIG = {
    'host': 'localhost',
    'database': 'sports_betting_ai',
    'user': 'sports_user',
    'password': 'sports_pass'
}

class RealNFLAnalyticsFetcher:
    """Fetch real NFL player analytics from ESPN and other APIs"""

    def __init__(self):
        self.espn_base = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
        self.sleeper_base = "https://api.sleeper.app/v1"

    async def fetch_nfl_season_stats(self, season: int = 2025) -> Dict:
        """Fetch real NFL season statistics from ESPN"""
        try:
            # ESPN provides comprehensive NFL data
            urls = [
                f"{self.espn_base}/athletes",  # Player roster data
                f"{self.espn_base}/scoreboard",  # Game data for context
                f"{self.espn_base}/teams",  # Team data
            ]

            results = {}
            async with aiohttp.ClientSession() as session:
                for url in urls:
                    try:
                        async with session.get(url, timeout=15) as response:
                            if response.status == 200:
                                data = await response.json()
                                if 'athletes' in url:
                                    results['players'] = data
                                elif 'scoreboard' in url:
                                    results['games'] = data
                                elif 'teams' in url:
                                    results['teams'] = data
                                print(f"✅ Fetched data from {url}")
                            else:
                                print(f"❌ Failed to fetch from {url}: {response.status}")
                    except Exception as e:
                        print(f"❌ Error fetching from {url}: {e}")

            return results

        except Exception as e:
            print(f"Error fetching NFL data: {e}")
            return {}

    async def fetch_sleeper_stats(self, season: int = 2025) -> Dict:
        """Fetch Sleeper player data for mapping and stats"""
        try:
            # Sleeper provides good player data and some stats
            # Note: Use 'regular' for regular season stats
            urls = [
                f"{self.sleeper_base}/players/nfl",  # All NFL players
                f"{self.sleeper_base}/stats/nfl/regular/{season}",  # Regular season stats
            ]

            results = {}
            async with aiohttp.ClientSession() as session:
                for url in urls:
                    try:
                        async with session.get(url, timeout=15) as response:
                            if response.status == 200:
                                data = await response.json()
                                if 'players' in url:
                                    results['players'] = data
                                elif 'stats' in url:
                                    results['stats'] = data
                                print(f"✅ Fetched Sleeper data from {url}")
                            else:
                                print(f"❌ Failed to fetch from {url}: {response.status}")
                    except Exception as e:
                        print(f"❌ Error fetching from {url}: {e}")

            return results

        except Exception as e:
            print(f"Error fetching Sleeper data: {e}")
            return {}

    def calculate_analytics_from_stats(self, player_stats: Dict, games_played: int) -> Dict:
        """Convert raw stats to analytics percentages"""
        analytics = {}

        # Get basic stats
        passing_attempts = player_stats.get('pass_att', 0)
        passing_yards = player_stats.get('pass_yd', 0)
        passing_tds = player_stats.get('pass_td', 0)

        rushing_attempts = player_stats.get('rush_att', 0)
        rushing_yards = player_stats.get('rush_yd', 0)
        rushing_tds = player_stats.get('rush_td', 0)

        receiving_targets = player_stats.get('rec_tgt', 0)
        receptions = player_stats.get('rec', 0)
        receiving_yards = player_stats.get('rec_yd', 0)
        receiving_tds = player_stats.get('rec_td', 0)

        # Calculate snap percentage (estimate based on usage)
        total_touches = rushing_attempts + receptions
        if total_touches > 0:
            # Estimate snap percentage based on touches per game
            touches_per_game = total_touches / max(games_played, 1)
            if touches_per_game >= 15:  # High usage player
                snap_percentage = min(85.0, 60.0 + touches_per_game)
            elif touches_per_game >= 8:  # Medium usage
                snap_percentage = min(70.0, 30.0 + touches_per_game * 2)
            else:  # Low usage
                snap_percentage = min(50.0, 10.0 + touches_per_game * 3)
        else:
            snap_percentage = 0.0

        # Calculate target share (estimate from league averages)
        if receiving_targets > 0:
            # NFL teams average ~35 pass attempts per game
            team_targets_estimate = 35 * games_played
            target_share = min(0.35, receiving_targets / max(team_targets_estimate, 1))
        else:
            target_share = 0.0

        # Calculate red zone share (estimate from TDs)
        total_tds = passing_tds + rushing_tds + receiving_tds
        if total_tds > 0:
            # Estimate red zone opportunities based on TDs
            red_zone_share = min(0.6, total_tds * 0.15)  # Rough estimate
        else:
            red_zone_share = 0.0

        # Calculate fantasy points (PPR)
        ppr_points = (
            passing_yards * 0.04 + passing_tds * 4 +
            rushing_yards * 0.1 + rushing_tds * 6 +
            receiving_yards * 0.1 + receiving_tds * 6 + receptions * 1
        )

        # Calculate efficiency metrics
        points_per_snap = ppr_points / max(snap_percentage * games_played, 1) if snap_percentage > 0 else 0
        points_per_target = ppr_points / max(receiving_targets, 1) if receiving_targets > 0 else 0
        points_per_touch = ppr_points / max(total_touches, 1) if total_touches > 0 else 0

        analytics = {
            'snap_percentage': round(snap_percentage, 1),
            'target_share': round(target_share, 4),
            'red_zone_share': round(red_zone_share, 4),
            'targets': receiving_targets,
            'receptions': receptions,
            'carries': rushing_attempts,
            'receiving_yards': receiving_yards,
            'rushing_yards': rushing_yards,
            'ppr_points': round(ppr_points, 1),
            'points_per_snap': round(points_per_snap, 3),
            'points_per_target': round(points_per_target, 3),
            'points_per_touch': round(points_per_touch, 3),
            'games_played': games_played
        }

        return analytics

    def map_player_to_database(self, player_data: Dict, sleeper_players: Dict) -> Optional[int]:
        """Map API player data to database player ID"""
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            # Try to find player by name and position
            player_name = player_data.get('displayName', '').strip()

            if not player_name:
                return None

            # Search in fantasy_players table
            search_patterns = [
                player_name,  # Exact match
                player_name.replace('.', ''),  # Remove periods
                player_name.replace(' Jr.', ''),  # Remove Jr.
                player_name.replace(' Sr.', ''),  # Remove Sr.
            ]

            for pattern in search_patterns:
                cur.execute("""
                    SELECT id FROM fantasy_players
                    WHERE LOWER(name) = LOWER(%s)
                    LIMIT 1
                """, (pattern,))

                result = cur.fetchone()
                if result:
                    return result[0]

            cur.close()
            conn.close()
            return None

        except Exception as e:
            print(f"Error mapping player {player_data.get('displayName', 'Unknown')}: {e}")
            return None

    async def populate_real_analytics(self, season: int = 2025):
        """Main function to populate real analytics data"""
        print(f"Starting real NFL analytics fetch for {season} season...")

        # Fetch data from APIs
        print("Fetching ESPN data...")
        espn_data = await self.fetch_nfl_season_stats(season)

        print("Fetching Sleeper data...")
        sleeper_data = await self.fetch_sleeper_stats(season)

        if not espn_data and not sleeper_data:
            print("❌ No data fetched from APIs")
            return False

        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            # Clear existing data for the season
            print(f"Clearing existing {season} data...")
            cur.execute("DELETE FROM player_analytics WHERE season = %s", (season,))
            conn.commit()

            # Process player data
            players_processed = 0
            records_inserted = 0

            # Use Sleeper stats if available (more comprehensive)
            if sleeper_data.get('stats'):
                sleeper_players = sleeper_data.get('players', {})

                for player_id, player_stats in sleeper_data['stats'].items():
                    try:
                        # Get player info from sleeper players data
                        player_info = sleeper_players.get(player_id, {})

                        if not player_info:
                            continue

                        # Map to database player
                        db_player_id = self.map_player_to_database(player_info, sleeper_players)

                        if not db_player_id:
                            continue

                        # Process each week's stats
                        for week_str, week_stats in player_stats.items():
                            try:
                                week = int(week_str)

                                # Calculate analytics from raw stats
                                analytics = self.calculate_analytics_from_stats(week_stats, 1)

                                # Insert analytics record
                                insert_query = """
                                    INSERT INTO player_analytics (
                                        player_id, week, season,
                                        snap_percentage, target_share, red_zone_share,
                                        targets, receptions, carries,
                                        receiving_yards, rushing_yards, ppr_points,
                                        points_per_snap, points_per_target, points_per_touch,
                                        created_at
                                    ) VALUES (
                                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                                    )
                                """

                                cur.execute(insert_query, (
                                    db_player_id, week, season,
                                    analytics['snap_percentage'], analytics['target_share'], analytics['red_zone_share'],
                                    analytics['targets'], analytics['receptions'], analytics['carries'],
                                    analytics['receiving_yards'], analytics['rushing_yards'], analytics['ppr_points'],
                                    analytics['points_per_snap'], analytics['points_per_target'], analytics['points_per_touch'],
                                    datetime.now()
                                ))

                                records_inserted += 1

                            except (ValueError, KeyError) as e:
                                continue  # Skip invalid week data

                        players_processed += 1

                        if players_processed % 50 == 0:
                            print(f"Processed {players_processed} players, inserted {records_inserted} records")
                            conn.commit()

                    except Exception as e:
                        print(f"Error processing player {player_id}: {e}")
                        continue

            # Final commit
            conn.commit()

            print(f"✅ Successfully processed {players_processed} players")
            print(f"✅ Inserted {records_inserted} analytics records for {season}")

            # Verify the data
            cur.execute("""
                SELECT COUNT(*) as total, COUNT(DISTINCT player_id) as players,
                       AVG(target_share) as avg_target_share, AVG(red_zone_share) as avg_rz_share
                FROM player_analytics WHERE season = %s
            """, (season,))

            verification = cur.fetchone()
            print(f"Verification - Total: {verification[0]}, Players: {verification[1]}")
            print(f"Avg Target Share: {verification[2]:.3f}, Avg RZ Share: {verification[3]:.3f}")

            cur.close()
            conn.close()

            return records_inserted > 0

        except Exception as e:
            print(f"Database error: {e}")
            return False

async def main():
    print("Starting real NFL analytics data fetch...")
    fetcher = RealNFLAnalyticsFetcher()

    # Try to fetch 2025 season data first, fall back to 2024 if needed
    success_2025 = await fetcher.populate_real_analytics(2025)

    if not success_2025:
        print("No 2025 data available, trying 2024 season...")
        success_2024 = await fetcher.populate_real_analytics(2024)

        if success_2024:
            print("✅ Successfully populated with 2024 real data!")
        else:
            print("❌ Failed to fetch any real data")
            sys.exit(1)
    else:
        print("✅ Successfully populated with 2025 real data!")

    print("Real data population completed!")

if __name__ == "__main__":
    asyncio.run(main())