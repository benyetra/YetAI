"""
CSV import endpoint for production database
"""

from fastapi import UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import csv
import io
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

async def import_csv_analytics(file: UploadFile, db: Session):
    """Import player analytics from CSV file"""
    try:
        # Read CSV content
        content = await file.read()
        csv_content = content.decode('utf-8')

        # Parse CSV
        csv_reader = csv.DictReader(io.StringIO(csv_content))

        # Clear existing data
        logger.info("Clearing existing player_analytics data...")
        db.execute(text("DELETE FROM player_analytics"))
        db.commit()

        # Insert new data
        records_inserted = 0
        for row in csv_reader:
            try:
                # Map CSV columns to database fields
                insert_query = text("""
                    INSERT INTO player_analytics (
                        id, player_id, week, season, game_date, opponent,
                        total_snaps, offensive_snaps, special_teams_snaps,
                        snap_percentage, snap_share_rank, targets, team_total_targets,
                        target_share, air_yards, air_yards_share, average_depth_of_target,
                        target_separation, red_zone_snaps, red_zone_targets,
                        red_zone_carries, red_zone_touches, red_zone_share,
                        red_zone_efficiency, routes_run, route_participation,
                        slot_rate, deep_target_rate, carries, rushing_yards,
                        goal_line_carries, carry_share, yards_before_contact,
                        yards_after_contact, broken_tackles, receptions,
                        receiving_yards, yards_after_catch, yards_after_catch_per_reception,
                        contested_catch_rate, drop_rate, team_pass_attempts,
                        team_rush_attempts, team_red_zone_attempts, game_script,
                        time_of_possession, ppr_points, half_ppr_points,
                        standard_points, points_per_snap, points_per_target,
                        points_per_touch, boom_rate, bust_rate, weekly_variance,
                        floor_score, ceiling_score, injury_designation,
                        snaps_missed_injury, games_missed_season, created_at
                    ) VALUES (
                        :id, :player_id, :week, :season, :game_date, :opponent,
                        :total_snaps, :offensive_snaps, :special_teams_snaps,
                        :snap_percentage, :snap_share_rank, :targets, :team_total_targets,
                        :target_share, :air_yards, :air_yards_share, :average_depth_of_target,
                        :target_separation, :red_zone_snaps, :red_zone_targets,
                        :red_zone_carries, :red_zone_touches, :red_zone_share,
                        :red_zone_efficiency, :routes_run, :route_participation,
                        :slot_rate, :deep_target_rate, :carries, :rushing_yards,
                        :goal_line_carries, :carry_share, :yards_before_contact,
                        :yards_after_contact, :broken_tackles, :receptions,
                        :receiving_yards, :yards_after_catch, :yards_after_catch_per_reception,
                        :contested_catch_rate, :drop_rate, :team_pass_attempts,
                        :team_rush_attempts, :team_red_zone_attempts, :game_script,
                        :time_of_possession, :ppr_points, :half_ppr_points,
                        :standard_points, :points_per_snap, :points_per_target,
                        :points_per_touch, :boom_rate, :bust_rate, :weekly_variance,
                        :floor_score, :ceiling_score, :injury_designation,
                        :snaps_missed_injury, :games_missed_season, :created_at
                    )
                """)

                # Convert empty strings to None and handle data types
                data = {}
                for key, value in row.items():
                    if value == '' or value == 'NULL':
                        data[key] = None
                    elif key in ['id', 'player_id', 'week', 'season', 'total_snaps', 'offensive_snaps',
                               'special_teams_snaps', 'snap_share_rank', 'targets', 'team_total_targets',
                               'air_yards', 'red_zone_snaps', 'red_zone_targets', 'red_zone_carries',
                               'red_zone_touches', 'routes_run', 'carries', 'rushing_yards',
                               'goal_line_carries', 'broken_tackles', 'receptions', 'receiving_yards',
                               'yards_after_catch', 'team_pass_attempts', 'team_rush_attempts',
                               'team_red_zone_attempts', 'snaps_missed_injury', 'games_missed_season']:
                        data[key] = int(float(value)) if value else None
                    elif key in ['snap_percentage', 'target_share', 'air_yards_share', 'average_depth_of_target',
                               'target_separation', 'red_zone_share', 'red_zone_efficiency', 'route_participation',
                               'slot_rate', 'deep_target_rate', 'carry_share', 'yards_before_contact',
                               'yards_after_contact', 'yards_after_catch_per_reception', 'contested_catch_rate',
                               'drop_rate', 'time_of_possession', 'ppr_points', 'half_ppr_points',
                               'standard_points', 'points_per_snap', 'points_per_target', 'points_per_touch',
                               'boom_rate', 'bust_rate', 'weekly_variance', 'floor_score', 'ceiling_score']:
                        data[key] = float(value) if value else None
                    elif key in ['game_date', 'created_at']:
                        data[key] = datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None
                    else:
                        data[key] = value if value else None

                db.execute(insert_query, data)
                records_inserted += 1

                if records_inserted % 1000 == 0:
                    db.commit()
                    logger.info(f"Inserted {records_inserted} records...")

            except Exception as e:
                logger.error(f"Error inserting row: {e}")
                continue

        # Final commit
        db.commit()

        logger.info(f"✅ Successfully imported {records_inserted} records from CSV")

        return {
            "status": "success",
            "message": f"Successfully imported {records_inserted} analytics records from CSV",
            "records_imported": records_inserted,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"CSV import failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to import CSV: {str(e)}")