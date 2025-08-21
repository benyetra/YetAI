"""Add Sleeper sync tables manually

Revision ID: sleeper_sync_manual
Revises: trade_analyzer_001
Create Date: 2025-01-21 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'sleeper_sync_manual'
down_revision = 'trade_analyzer_001'
branch_labels = None
depends_on = None

def upgrade():
    # Add sleeper_user_id to users table
    op.add_column('users', sa.Column('sleeper_user_id', sa.String(length=255), nullable=True))
    
    # Create sleeper_leagues table
    op.create_table('sleeper_leagues',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('sleeper_league_id', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('season', sa.Integer(), nullable=False),
    sa.Column('total_rosters', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=True),
    sa.Column('scoring_type', sa.String(length=50), nullable=True),
    sa.Column('roster_positions', sa.JSON(), nullable=True),
    sa.Column('scoring_settings', sa.JSON(), nullable=True),
    sa.Column('waiver_settings', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('last_synced', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sleeper_leagues_id'), 'sleeper_leagues', ['id'], unique=False)
    
    # Create sleeper_rosters table
    op.create_table('sleeper_rosters',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('league_id', sa.Integer(), nullable=False),
    sa.Column('sleeper_roster_id', sa.String(length=255), nullable=False),
    sa.Column('sleeper_owner_id', sa.String(length=255), nullable=False),
    sa.Column('team_name', sa.String(length=255), nullable=True),
    sa.Column('owner_name', sa.String(length=255), nullable=True),
    sa.Column('wins', sa.Integer(), nullable=True),
    sa.Column('losses', sa.Integer(), nullable=True),
    sa.Column('ties', sa.Integer(), nullable=True),
    sa.Column('points_for', sa.Float(), nullable=True),
    sa.Column('points_against', sa.Float(), nullable=True),
    sa.Column('waiver_position', sa.Integer(), nullable=True),
    sa.Column('players', sa.JSON(), nullable=True),
    sa.Column('starters', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('last_synced', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['league_id'], ['sleeper_leagues.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sleeper_rosters_id'), 'sleeper_rosters', ['id'], unique=False)
    
    # Create sleeper_players table
    op.create_table('sleeper_players',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sleeper_player_id', sa.String(length=255), nullable=False),
    sa.Column('first_name', sa.String(length=100), nullable=True),
    sa.Column('last_name', sa.String(length=100), nullable=True),
    sa.Column('full_name', sa.String(length=255), nullable=True),
    sa.Column('position', sa.String(length=10), nullable=True),
    sa.Column('team', sa.String(length=10), nullable=True),
    sa.Column('age', sa.Integer(), nullable=True),
    sa.Column('height', sa.String(length=10), nullable=True),
    sa.Column('weight', sa.String(length=10), nullable=True),
    sa.Column('years_exp', sa.Integer(), nullable=True),
    sa.Column('college', sa.String(length=255), nullable=True),
    sa.Column('fantasy_positions', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=True),
    sa.Column('injury_status', sa.String(length=50), nullable=True),
    sa.Column('depth_chart_position', sa.Integer(), nullable=True),
    sa.Column('depth_chart_order', sa.Integer(), nullable=True),
    sa.Column('search_rank', sa.Integer(), nullable=True),
    sa.Column('hashtag', sa.String(length=255), nullable=True),
    sa.Column('espn_id', sa.String(length=50), nullable=True),
    sa.Column('yahoo_id', sa.String(length=50), nullable=True),
    sa.Column('fantasy_data_id', sa.String(length=50), nullable=True),
    sa.Column('rotoworld_id', sa.String(length=50), nullable=True),
    sa.Column('rotowire_id', sa.String(length=50), nullable=True),
    sa.Column('sportradar_id', sa.String(length=50), nullable=True),
    sa.Column('stats_id', sa.String(length=50), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('last_synced', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sleeper_players_id'), 'sleeper_players', ['id'], unique=False)
    op.create_index(op.f('ix_sleeper_players_sleeper_player_id'), 'sleeper_players', ['sleeper_player_id'], unique=True)

def downgrade():
    # Remove the tables and column we added
    op.drop_index(op.f('ix_sleeper_players_sleeper_player_id'), table_name='sleeper_players')
    op.drop_index(op.f('ix_sleeper_players_id'), table_name='sleeper_players')
    op.drop_table('sleeper_players')
    op.drop_index(op.f('ix_sleeper_rosters_id'), table_name='sleeper_rosters')
    op.drop_table('sleeper_rosters')
    op.drop_index(op.f('ix_sleeper_leagues_id'), table_name='sleeper_leagues')
    op.drop_table('sleeper_leagues')
    op.drop_column('users', 'sleeper_user_id')