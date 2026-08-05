"""Ballpark Pal daily snapshot tables."""

from alembic import op
import sqlalchemy as sa

revision = "20260805_bpp_snapshots"
down_revision = "20260805_pitcher_arch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bpp_game_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slate_date", sa.Date(), nullable=False),
        sa.Column("bpp_game_id", sa.Integer(), nullable=False),
        sa.Column("game_pk", sa.Integer(), nullable=True),
        sa.Column("team_away_id", sa.Integer(), nullable=False),
        sa.Column("team_home_id", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("averages_json", sa.JSON(), nullable=False),
        sa.Column("probabilities_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "slate_date", "bpp_game_id", name="uq_bpp_game_snapshot_date_game"
        ),
    )
    op.create_table(
        "bpp_player_proj_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slate_date", sa.Date(), nullable=False),
        sa.Column("bpp_game_id", sa.Integer(), nullable=False),
        sa.Column("game_pk", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("averages_json", sa.JSON(), nullable=False),
        sa.Column("selected_probs_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('batter', 'pitcher', 'team')",
            name="ck_bpp_player_proj_snapshot_role",
        ),
        sa.UniqueConstraint(
            "slate_date",
            "bpp_game_id",
            "player_id",
            "role",
            name="uq_bpp_player_proj_snapshot_date_game_player_role",
        ),
    )
    op.create_table(
        "bpp_park_factor_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slate_date", sa.Date(), nullable=False),
        sa.Column("bpp_game_id", sa.Integer(), nullable=False),
        sa.Column("game_pk", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("factors_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "scope IN ('game', 'hitter')",
            name="ck_bpp_park_factor_snapshot_scope",
        ),
        sa.UniqueConstraint(
            "slate_date",
            "bpp_game_id",
            "scope",
            "player_id",
            name="uq_bpp_park_factor_snapshot_date_game_scope_player",
        ),
    )
    op.create_table(
        "bpp_matchup_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slate_date", sa.Date(), nullable=False),
        sa.Column("bpp_game_id", sa.Integer(), nullable=False),
        sa.Column("game_pk", sa.Integer(), nullable=False),
        sa.Column("batter_id", sa.Integer(), nullable=False),
        sa.Column("pitcher_id", sa.Integer(), nullable=False),
        sa.Column("probs_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "slate_date",
            "batter_id",
            "pitcher_id",
            name="uq_bpp_matchup_snapshot_date_batter_pitcher",
        ),
    )


def downgrade() -> None:
    op.drop_table("bpp_matchup_snapshots")
    op.drop_table("bpp_park_factor_snapshots")
    op.drop_table("bpp_player_proj_snapshots")
    op.drop_table("bpp_game_snapshots")
