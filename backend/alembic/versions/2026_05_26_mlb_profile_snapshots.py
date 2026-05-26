"""MLB batter/pitcher profile snapshot tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260526_mlb_profiles"
down_revision = "2026_05_26_game_spread_rec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mlb_pitcher_profile_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pitcher_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("window", sa.String(16), nullable=False),
        sa.Column("profile_version", sa.String(32), nullable=False),
        sa.Column("hand", sa.String(1), nullable=True),
        sa.Column("n_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("profile", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_mlb_pitcher_profile_pitcher_date",
        "mlb_pitcher_profile_snapshots",
        ["pitcher_id", "as_of_date"],
    )
    op.create_table(
        "mlb_batter_profile_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batter_id", sa.Integer(), nullable=False),
        sa.Column("vs_hand", sa.String(1), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("window", sa.String(16), nullable=False),
        sa.Column("profile_version", sa.String(32), nullable=False),
        sa.Column("n_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("profile", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_mlb_batter_profile_batter_date",
        "mlb_batter_profile_snapshots",
        ["batter_id", "as_of_date"],
    )


def downgrade() -> None:
    op.drop_table("mlb_batter_profile_snapshots")
    op.drop_table("mlb_pitcher_profile_snapshots")
