"""MLB player archetype assignments for profile cold-start."""

from alembic import op
import sqlalchemy as sa

revision = "20260526_mlb_archetypes"
down_revision = "20260526_hitter_profile_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mlb_player_archetypes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("archetype_id", sa.String(32), nullable=False),
        sa.Column("n_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_mlb_player_archetypes_player_season",
        "mlb_player_archetypes",
        ["player_id", "season"],
    )


def downgrade() -> None:
    op.drop_table("mlb_player_archetypes")
