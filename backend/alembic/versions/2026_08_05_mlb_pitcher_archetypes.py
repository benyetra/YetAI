"""MLB pitcher archetype assignments for profile cold-start."""

from alembic import op
import sqlalchemy as sa

revision = "20260805_pitcher_arch"
down_revision = "20260805_k_matchup_src"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mlb_pitcher_archetypes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pitcher_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("archetype_id", sa.String(32), nullable=False),
        sa.Column("n_pitches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_fb_velo", sa.Float(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "pitcher_id", "season", name="uq_mlb_pitcher_archetype_season"
        ),
    )
    op.create_index(
        "ix_mlb_pitcher_archetypes_pitcher_season",
        "mlb_pitcher_archetypes",
        ["pitcher_id", "season"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mlb_pitcher_archetypes_pitcher_season",
        table_name="mlb_pitcher_archetypes",
    )
    op.drop_table("mlb_pitcher_archetypes")
