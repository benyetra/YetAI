"""Add PlayerAnalytics and PlayerTrends tables

Revision ID: player_analytics_001
Revises: cd7b2d25598c
Create Date: 2025-08-20 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'player_analytics_001'
down_revision = 'cd7b2d25598c'
branch_labels = None
depends_on = None


def upgrade():
    # Create PlayerAnalytics table
    op.create_table('player_analytics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('season', sa.Integer(), nullable=False),
        sa.Column('game_date', sa.DateTime(), nullable=True),
        sa.Column('opponent', sa.String(length=10), nullable=True),
        
        # Snap Count Analytics
        sa.Column('total_snaps', sa.Integer(), nullable=True),
        sa.Column('offensive_snaps', sa.Integer(), nullable=True),
        sa.Column('special_teams_snaps', sa.Integer(), nullable=True),
        sa.Column('snap_percentage', sa.Float(), nullable=True),
        sa.Column('snap_share_rank', sa.Integer(), nullable=True),
        
        # Target Share Analytics
        sa.Column('targets', sa.Integer(), default=0),
        sa.Column('team_total_targets', sa.Integer(), nullable=True),
        sa.Column('target_share', sa.Float(), nullable=True),
        sa.Column('air_yards', sa.Integer(), nullable=True),
        sa.Column('air_yards_share', sa.Float(), nullable=True),
        sa.Column('average_depth_of_target', sa.Float(), nullable=True),
        sa.Column('target_separation', sa.Float(), nullable=True),
        
        # Red Zone Usage
        sa.Column('red_zone_snaps', sa.Integer(), default=0),
        sa.Column('red_zone_targets', sa.Integer(), default=0),
        sa.Column('red_zone_carries', sa.Integer(), default=0),
        sa.Column('red_zone_touches', sa.Integer(), default=0),
        sa.Column('red_zone_share', sa.Float(), nullable=True),
        sa.Column('red_zone_efficiency', sa.Float(), nullable=True),
        
        # Route Running
        sa.Column('routes_run', sa.Integer(), default=0),
        sa.Column('route_participation', sa.Float(), nullable=True),
        sa.Column('slot_rate', sa.Float(), nullable=True),
        sa.Column('deep_target_rate', sa.Float(), nullable=True),
        
        # Rushing Usage
        sa.Column('carries', sa.Integer(), default=0),
        sa.Column('rushing_yards', sa.Integer(), default=0),
        sa.Column('goal_line_carries', sa.Integer(), default=0),
        sa.Column('carry_share', sa.Float(), nullable=True),
        sa.Column('yards_before_contact', sa.Float(), nullable=True),
        sa.Column('yards_after_contact', sa.Float(), nullable=True),
        sa.Column('broken_tackles', sa.Integer(), default=0),
        
        # Receiving Production
        sa.Column('receptions', sa.Integer(), default=0),
        sa.Column('receiving_yards', sa.Integer(), default=0),
        sa.Column('yards_after_catch', sa.Integer(), default=0),
        sa.Column('yards_after_catch_per_reception', sa.Float(), nullable=True),
        sa.Column('contested_catch_rate', sa.Float(), nullable=True),
        sa.Column('drop_rate', sa.Float(), nullable=True),
        
        # Game Context
        sa.Column('team_pass_attempts', sa.Integer(), nullable=True),
        sa.Column('team_rush_attempts', sa.Integer(), nullable=True),
        sa.Column('team_red_zone_attempts', sa.Integer(), nullable=True),
        sa.Column('game_script', sa.Float(), nullable=True),
        sa.Column('time_of_possession', sa.Float(), nullable=True),
        
        # Advanced Efficiency Metrics
        sa.Column('ppr_points', sa.Float(), nullable=True),
        sa.Column('half_ppr_points', sa.Float(), nullable=True),
        sa.Column('standard_points', sa.Float(), nullable=True),
        sa.Column('points_per_snap', sa.Float(), nullable=True),
        sa.Column('points_per_target', sa.Float(), nullable=True),
        sa.Column('points_per_touch', sa.Float(), nullable=True),
        
        # Consistency Metrics
        sa.Column('boom_rate', sa.Float(), nullable=True),
        sa.Column('bust_rate', sa.Float(), nullable=True),
        sa.Column('weekly_variance', sa.Float(), nullable=True),
        sa.Column('floor_score', sa.Float(), nullable=True),
        sa.Column('ceiling_score', sa.Float(), nullable=True),
        
        # Injury/Availability
        sa.Column('injury_designation', sa.String(length=20), nullable=True),
        sa.Column('snaps_missed_injury', sa.Integer(), default=0),
        sa.Column('games_missed_season', sa.Integer(), default=0),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['player_id'], ['fantasy_players.id'])
    )
    
    # Create PlayerTrends table
    op.create_table('player_trends',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('season', sa.Integer(), nullable=False),
        sa.Column('trend_type', sa.String(length=50), nullable=False),
        sa.Column('period_start', sa.Integer(), nullable=True),
        sa.Column('period_end', sa.Integer(), nullable=True),
        
        # Usage Trends
        sa.Column('snap_share_trend', sa.Float(), nullable=True),
        sa.Column('target_share_trend', sa.Float(), nullable=True),
        sa.Column('red_zone_usage_trend', sa.Float(), nullable=True),
        sa.Column('carry_share_trend', sa.Float(), nullable=True),
        
        # Performance Trends
        sa.Column('fantasy_points_trend', sa.Float(), nullable=True),
        sa.Column('efficiency_trend', sa.Float(), nullable=True),
        sa.Column('consistency_trend', sa.Float(), nullable=True),
        
        # Context Changes
        sa.Column('role_change_indicator', sa.Boolean(), default=False),
        sa.Column('role_change_description', sa.String(length=500), nullable=True),
        sa.Column('opportunity_change_score', sa.Float(), nullable=True),
        
        # Predictive Metrics
        sa.Column('momentum_score', sa.Float(), nullable=True),
        sa.Column('sustainability_score', sa.Float(), nullable=True),
        sa.Column('buy_low_indicator', sa.Boolean(), default=False),
        sa.Column('sell_high_indicator', sa.Boolean(), default=False),
        
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['player_id'], ['fantasy_players.id'])
    )
    
    # Create indexes
    op.create_index('idx_player_analytics_player_week', 'player_analytics', ['player_id', 'week', 'season'])
    op.create_index('idx_player_trends_player_season', 'player_trends', ['player_id', 'season'])
    op.create_index('idx_player_analytics_snap_share', 'player_analytics', ['player_id', 'snap_percentage'])
    op.create_index('idx_player_analytics_target_share', 'player_analytics', ['player_id', 'target_share'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_player_analytics_target_share')
    op.drop_index('idx_player_analytics_snap_share')
    op.drop_index('idx_player_trends_player_season')
    op.drop_index('idx_player_analytics_player_week')
    
    # Drop tables
    op.drop_table('player_trends')
    op.drop_table('player_analytics')