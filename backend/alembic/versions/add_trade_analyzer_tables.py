"""Add trade analyzer tables

Revision ID: trade_analyzer_001
Revises: player_analytics_001
Create Date: 2024-08-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'trade_analyzer_001'
down_revision = 'player_analytics_001'
branch_labels = None
depends_on = None

def upgrade():
    # Create draft_picks table
    op.create_table('draft_picks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('league_id', sa.Integer(), nullable=False),
        sa.Column('current_owner_team_id', sa.Integer(), nullable=False),
        sa.Column('original_owner_team_id', sa.Integer(), nullable=False),
        sa.Column('season', sa.Integer(), nullable=False),
        sa.Column('round_number', sa.Integer(), nullable=False),
        sa.Column('pick_number', sa.Integer(), nullable=True),
        sa.Column('is_tradeable', sa.Boolean(), nullable=True, default=True),
        sa.Column('trade_deadline', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.ForeignKeyConstraint(['current_owner_team_id'], ['fantasy_teams.id'], ),
        sa.ForeignKeyConstraint(['league_id'], ['fantasy_leagues.id'], ),
        sa.ForeignKeyConstraint(['original_owner_team_id'], ['fantasy_teams.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_draft_picks_id', 'draft_picks', ['id'], unique=False)
    op.create_index('idx_draft_picks_league_season', 'draft_picks', ['league_id', 'season'], unique=False)

    # Create trades table
    op.create_table('trades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('league_id', sa.Integer(), nullable=False),
        sa.Column('team1_id', sa.Integer(), nullable=False),
        sa.Column('team2_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('PROPOSED', 'PENDING', 'ACCEPTED', 'DECLINED', 'EXPIRED', 'CANCELLED', name='tradestatus'), nullable=True, default='PROPOSED'),
        sa.Column('proposed_by_team_id', sa.Integer(), nullable=False),
        sa.Column('team1_gives', sa.JSON(), nullable=True),
        sa.Column('team2_gives', sa.JSON(), nullable=True),
        sa.Column('proposed_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('trade_reason', sa.Text(), nullable=True),
        sa.Column('is_ai_suggested', sa.Boolean(), nullable=True, default=False),
        sa.Column('veto_deadline', sa.DateTime(), nullable=True),
        sa.Column('veto_count', sa.Integer(), nullable=True, default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.ForeignKeyConstraint(['league_id'], ['fantasy_leagues.id'], ),
        sa.ForeignKeyConstraint(['proposed_by_team_id'], ['fantasy_teams.id'], ),
        sa.ForeignKeyConstraint(['team1_id'], ['fantasy_teams.id'], ),
        sa.ForeignKeyConstraint(['team2_id'], ['fantasy_teams.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_trades_id', 'trades', ['id'], unique=False)
    op.create_index('idx_trades_league_status', 'trades', ['league_id', 'status'], unique=False)
    op.create_index('idx_trades_teams', 'trades', ['team1_id', 'team2_id'], unique=False)

    # Create trade_evaluations table
    op.create_table('trade_evaluations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trade_id', sa.Integer(), nullable=False),
        sa.Column('team1_grade', sa.Enum('A_PLUS', 'A', 'A_MINUS', 'B_PLUS', 'B', 'B_MINUS', 'C_PLUS', 'C', 'C_MINUS', 'D', 'F', name='tradegrade'), nullable=False),
        sa.Column('team2_grade', sa.Enum('A_PLUS', 'A', 'A_MINUS', 'B_PLUS', 'B', 'B_MINUS', 'C_PLUS', 'C', 'C_MINUS', 'D', 'F', name='tradegrade'), nullable=False),
        sa.Column('team1_analysis', sa.JSON(), nullable=True),
        sa.Column('team2_analysis', sa.JSON(), nullable=True),
        sa.Column('team1_value_given', sa.Float(), nullable=True),
        sa.Column('team1_value_received', sa.Float(), nullable=True),
        sa.Column('team2_value_given', sa.Float(), nullable=True),
        sa.Column('team2_value_received', sa.Float(), nullable=True),
        sa.Column('trade_context', sa.JSON(), nullable=True),
        sa.Column('fairness_score', sa.Float(), nullable=True),
        sa.Column('ai_summary', sa.Text(), nullable=True),
        sa.Column('key_factors', sa.JSON(), nullable=True),
        sa.Column('evaluation_version', sa.String(length=10), nullable=True, default='1.0'),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.ForeignKeyConstraint(['trade_id'], ['trades.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_trade_evaluations_id', 'trade_evaluations', ['id'], unique=False)
    op.create_index('idx_trade_evaluations_trade', 'trade_evaluations', ['trade_id'], unique=False)

    # Create trade_recommendations table
    op.create_table('trade_recommendations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('league_id', sa.Integer(), nullable=False),
        sa.Column('requesting_team_id', sa.Integer(), nullable=False),
        sa.Column('target_team_id', sa.Integer(), nullable=False),
        sa.Column('trade_id', sa.Integer(), nullable=True),
        sa.Column('recommendation_type', sa.String(length=50), nullable=True),
        sa.Column('priority_score', sa.Float(), nullable=True),
        sa.Column('suggested_trade', sa.JSON(), nullable=True),
        sa.Column('mutual_benefit_score', sa.Float(), nullable=True),
        sa.Column('likelihood_accepted', sa.Float(), nullable=True),
        sa.Column('recommendation_reason', sa.Text(), nullable=True),
        sa.Column('timing_factor', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
        sa.Column('was_proposed', sa.Boolean(), nullable=True, default=False),
        sa.Column('user_dismissed', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['league_id'], ['fantasy_leagues.id'], ),
        sa.ForeignKeyConstraint(['requesting_team_id'], ['fantasy_teams.id'], ),
        sa.ForeignKeyConstraint(['target_team_id'], ['fantasy_teams.id'], ),
        sa.ForeignKeyConstraint(['trade_id'], ['trades.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_trade_recommendations_id', 'trade_recommendations', ['id'], unique=False)
    op.create_index('idx_trade_recommendations_active', 'trade_recommendations', ['league_id', 'is_active'], unique=False)

    # Create player_values table
    op.create_table('player_values',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('league_id', sa.Integer(), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('season', sa.Integer(), nullable=False),
        sa.Column('rest_of_season_value', sa.Float(), nullable=True),
        sa.Column('dynasty_value', sa.Float(), nullable=True),
        sa.Column('redraft_value', sa.Float(), nullable=True),
        sa.Column('ppr_value', sa.Float(), nullable=True),
        sa.Column('standard_value', sa.Float(), nullable=True),
        sa.Column('superflex_value', sa.Float(), nullable=True),
        sa.Column('trade_frequency', sa.Float(), nullable=True),
        sa.Column('buy_low_indicator', sa.Boolean(), nullable=True, default=False),
        sa.Column('sell_high_indicator', sa.Boolean(), nullable=True, default=False),
        sa.Column('value_volatility', sa.Float(), nullable=True),
        sa.Column('injury_risk_factor', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.ForeignKeyConstraint(['league_id'], ['fantasy_leagues.id'], ),
        sa.ForeignKeyConstraint(['player_id'], ['fantasy_players.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_player_values_id', 'player_values', ['id'], unique=False)
    op.create_index('idx_player_values_league_week', 'player_values', ['league_id', 'week', 'season'], unique=False)

    # Create team_needs_analysis table
    op.create_table('team_needs_analysis',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('season', sa.Integer(), nullable=False),
        sa.Column('position_strengths', sa.JSON(), nullable=True),
        sa.Column('position_needs', sa.JSON(), nullable=True),
        sa.Column('starter_quality', sa.Float(), nullable=True),
        sa.Column('bench_depth', sa.Float(), nullable=True),
        sa.Column('age_profile', sa.Float(), nullable=True),
        sa.Column('championship_contender', sa.Boolean(), nullable=True, default=False),
        sa.Column('should_rebuild', sa.Boolean(), nullable=True, default=False),
        sa.Column('win_now_mode', sa.Boolean(), nullable=True, default=False),
        sa.Column('preferred_trade_types', sa.JSON(), nullable=True),
        sa.Column('assets_to_sell', sa.JSON(), nullable=True),
        sa.Column('targets_to_acquire', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, default=sa.func.now()),
        sa.ForeignKeyConstraint(['team_id'], ['fantasy_teams.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_team_needs_analysis_id', 'team_needs_analysis', ['id'], unique=False)
    op.create_index('idx_team_needs_analysis_team_week', 'team_needs_analysis', ['team_id', 'week'], unique=False)


def downgrade():
    # Drop trade analyzer tables in reverse order
    op.drop_index('idx_team_needs_analysis_team_week', table_name='team_needs_analysis')
    op.drop_index('ix_team_needs_analysis_id', table_name='team_needs_analysis')
    op.drop_table('team_needs_analysis')

    op.drop_index('idx_player_values_league_week', table_name='player_values')
    op.drop_index('ix_player_values_id', table_name='player_values')
    op.drop_table('player_values')

    op.drop_index('idx_trade_recommendations_active', table_name='trade_recommendations')
    op.drop_index('ix_trade_recommendations_id', table_name='trade_recommendations')
    op.drop_table('trade_recommendations')

    op.drop_index('idx_trade_evaluations_trade', table_name='trade_evaluations')
    op.drop_index('ix_trade_evaluations_id', table_name='trade_evaluations')
    op.drop_table('trade_evaluations')

    op.drop_index('idx_trades_teams', table_name='trades')
    op.drop_index('idx_trades_league_status', table_name='trades')
    op.drop_index('ix_trades_id', table_name='trades')
    op.drop_table('trades')

    op.drop_index('idx_draft_picks_league_season', table_name='draft_picks')
    op.drop_index('ix_draft_picks_id', table_name='draft_picks')
    op.drop_table('draft_picks')