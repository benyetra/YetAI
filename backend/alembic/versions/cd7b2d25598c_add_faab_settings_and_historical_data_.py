"""Add FAAB settings and historical data support

Revision ID: cd7b2d25598c
Revises: f1c7135a00e0
Create Date: 2025-08-20 07:07:47.404532

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cd7b2d25598c"
down_revision: Union[str, Sequence[str], None] = "f1c7135a00e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns to fantasy_leagues table for FAAB support
    op.add_column(
        "fantasy_leagues", sa.Column("waiver_type", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "fantasy_leagues", sa.Column("waiver_budget", sa.Integer(), nullable=True)
    )
    op.add_column(
        "fantasy_leagues", sa.Column("waiver_clear_days", sa.Integer(), nullable=True)
    )
    op.add_column(
        "fantasy_leagues", sa.Column("roster_positions", sa.JSON(), nullable=True)
    )

    # Create league_historical_data table
    op.create_table(
        "league_historical_data",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("team_count", sa.Integer(), nullable=True),
        sa.Column("waiver_type", sa.String(length=50), nullable=True),
        sa.Column("waiver_budget", sa.Integer(), nullable=True),
        sa.Column("scoring_type", sa.String(length=50), nullable=True),
        sa.Column("teams_data", sa.JSON(), nullable=True),
        sa.Column("transactions_data", sa.JSON(), nullable=True),
        sa.Column("standings_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["fantasy_leagues.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_historical_data_league_season",
        "league_historical_data",
        ["league_id", "season"],
        unique=False,
    )
    op.create_index(
        op.f("ix_league_historical_data_id"),
        "league_historical_data",
        ["id"],
        unique=False,
    )

    # Create competitor_analysis table
    op.create_table(
        "competitor_analysis",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("league_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("seasons_analyzed", sa.JSON(), nullable=True),
        sa.Column("avg_waiver_adds_per_season", sa.Float(), nullable=True),
        sa.Column("preferred_positions", sa.JSON(), nullable=True),
        sa.Column("waiver_aggressiveness_score", sa.Float(), nullable=True),
        sa.Column("avg_faab_spent_per_season", sa.Float(), nullable=True),
        sa.Column("high_faab_bid_threshold", sa.Float(), nullable=True),
        sa.Column("faab_conservation_tendency", sa.String(length=20), nullable=True),
        sa.Column("common_position_needs", sa.JSON(), nullable=True),
        sa.Column("panic_drop_tendency", sa.Float(), nullable=True),
        sa.Column("waiver_claim_day_preferences", sa.JSON(), nullable=True),
        sa.Column("season_phase_activity", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["league_id"],
            ["fantasy_leagues.id"],
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["fantasy_teams.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_competitor_analysis_league_team",
        "competitor_analysis",
        ["league_id", "team_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_competitor_analysis_id"), "competitor_analysis", ["id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop new tables
    op.drop_index(op.f("ix_competitor_analysis_id"), table_name="competitor_analysis")
    op.drop_index(
        "idx_competitor_analysis_league_team", table_name="competitor_analysis"
    )
    op.drop_table("competitor_analysis")

    op.drop_index(
        op.f("ix_league_historical_data_id"), table_name="league_historical_data"
    )
    op.drop_index(
        "idx_historical_data_league_season", table_name="league_historical_data"
    )
    op.drop_table("league_historical_data")

    # Drop new columns from fantasy_leagues
    op.drop_column("fantasy_leagues", "roster_positions")
    op.drop_column("fantasy_leagues", "waiver_clear_days")
    op.drop_column("fantasy_leagues", "waiver_budget")
    op.drop_column("fantasy_leagues", "waiver_type")
