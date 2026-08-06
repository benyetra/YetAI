"""League Vault pilot lv_* tables."""

from alembic import op
import sqlalchemy as sa

revision = "20260806_league_vault"
down_revision = "20260805_bpp_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lv_league_lineage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("root_platform_league_id", sa.String(length=64), nullable=False),
        sa.Column("season_league_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_synced", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "platform",
            "root_platform_league_id",
            name="uq_lv_lineage_platform_root",
        ),
    )
    op.create_index(
        op.f("ix_lv_league_lineage_id"), "lv_league_lineage", ["id"], unique=False
    )

    op.create_table(
        "lv_sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lineage_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("tagline", sa.String(length=512), nullable=True),
        sa.Column("first_season", sa.Integer(), nullable=True),
        sa.Column("latest_season", sa.Integer(), nullable=True),
        sa.Column("last_place_label", sa.String(length=64), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lineage_id"], ["lv_league_lineage.id"]),
        sa.UniqueConstraint("lineage_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_lv_sites_id"), "lv_sites", ["id"], unique=False)
    op.create_index(op.f("ix_lv_sites_slug"), "lv_sites", ["slug"], unique=True)

    op.create_table(
        "lv_managers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lineage_id", sa.Integer(), nullable=False),
        sa.Column("platform_user_id", sa.String(length=64), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("first_season", sa.Integer(), nullable=True),
        sa.Column("last_season", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["lineage_id"], ["lv_league_lineage.id"]),
        sa.UniqueConstraint(
            "lineage_id",
            "platform_user_id",
            name="uq_lv_manager_lineage_platform_user",
        ),
    )
    op.create_index(op.f("ix_lv_managers_id"), "lv_managers", ["id"], unique=False)

    op.create_table(
        "lv_seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lineage_id", sa.Integer(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("platform_league_id", sa.String(length=64), nullable=False),
        sa.Column("team_count", sa.Integer(), nullable=True),
        sa.Column("playoff_teams", sa.Integer(), nullable=True),
        sa.Column("regular_season_weeks", sa.Integer(), nullable=True),
        sa.Column("scoring_settings", sa.JSON(), nullable=True),
        sa.Column("roster_positions", sa.JSON(), nullable=True),
        sa.Column("champion_manager_id", sa.Integer(), nullable=True),
        sa.Column("runner_up_manager_id", sa.Integer(), nullable=True),
        sa.Column("last_place_manager_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["champion_manager_id"], ["lv_managers.id"]),
        sa.ForeignKeyConstraint(["last_place_manager_id"], ["lv_managers.id"]),
        sa.ForeignKeyConstraint(["lineage_id"], ["lv_league_lineage.id"]),
        sa.ForeignKeyConstraint(["runner_up_manager_id"], ["lv_managers.id"]),
        sa.UniqueConstraint("lineage_id", "season", name="uq_lv_season_lineage_season"),
    )
    op.create_index(op.f("ix_lv_seasons_id"), "lv_seasons", ["id"], unique=False)

    op.create_table(
        "lv_sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lineage_id", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("root_platform_league_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["lineage_id"], ["lv_league_lineage.id"]),
    )
    op.create_index(op.f("ix_lv_sync_jobs_id"), "lv_sync_jobs", ["id"], unique=False)

    op.create_table(
        "lv_teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("manager_id", sa.Integer(), nullable=False),
        sa.Column("platform_roster_id", sa.String(length=64), nullable=False),
        sa.Column("team_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("ties", sa.Integer(), nullable=False),
        sa.Column("points_for", sa.Float(), nullable=False),
        sa.Column("points_against", sa.Float(), nullable=False),
        sa.Column("final_rank", sa.Integer(), nullable=True),
        sa.Column("playoff_seed", sa.Integer(), nullable=True),
        sa.Column("all_play_wins", sa.Integer(), nullable=True),
        sa.Column("all_play_losses", sa.Integer(), nullable=True),
        sa.Column("luck_differential", sa.Float(), nullable=True),
        sa.Column("moves", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["manager_id"], ["lv_managers.id"]),
        sa.ForeignKeyConstraint(["season_id"], ["lv_seasons.id"]),
        sa.UniqueConstraint(
            "season_id",
            "platform_roster_id",
            name="uq_lv_team_season_roster",
        ),
    )
    op.create_index(op.f("ix_lv_teams_id"), "lv_teams", ["id"], unique=False)

    op.create_table(
        "lv_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("platform_draft_id", sa.String(length=64), nullable=True),
        sa.Column("draft_type", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["season_id"], ["lv_seasons.id"]),
    )
    op.create_index(op.f("ix_lv_drafts_id"), "lv_drafts", ["id"], unique=False)

    op.create_table(
        "lv_matchups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("platform_matchup_id", sa.String(length=64), nullable=True),
        sa.Column("is_playoff", sa.Boolean(), nullable=False),
        sa.Column("playoff_round", sa.Integer(), nullable=True),
        sa.Column("bracket", sa.String(length=32), nullable=True),
        sa.Column("team_a_id", sa.Integer(), nullable=False),
        sa.Column("team_b_id", sa.Integer(), nullable=False),
        sa.Column("team_a_score", sa.Float(), nullable=True),
        sa.Column("team_b_score", sa.Float(), nullable=True),
        sa.Column("winner_team_id", sa.Integer(), nullable=True),
        sa.Column("margin", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["season_id"], ["lv_seasons.id"]),
        sa.ForeignKeyConstraint(["team_a_id"], ["lv_teams.id"]),
        sa.ForeignKeyConstraint(["team_b_id"], ["lv_teams.id"]),
        sa.ForeignKeyConstraint(["winner_team_id"], ["lv_teams.id"]),
    )
    op.create_index(op.f("ix_lv_matchups_id"), "lv_matchups", ["id"], unique=False)

    op.create_table(
        "lv_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lineage_id", sa.Integer(), nullable=False),
        sa.Column("record_key", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=True),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("manager_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lineage_id"], ["lv_league_lineage.id"]),
        sa.ForeignKeyConstraint(["manager_id"], ["lv_managers.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["lv_teams.id"]),
    )
    op.create_index(op.f("ix_lv_records_id"), "lv_records", ["id"], unique=False)
    op.create_index("ix_lv_records_lineage_id", "lv_records", ["lineage_id"])
    op.create_index("ix_lv_records_record_key", "lv_records", ["record_key"])

    op.create_table(
        "lv_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=True),
        sa.Column("platform_transaction_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("created_at_ts", sa.BigInteger(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("team_ids", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["season_id"], ["lv_seasons.id"]),
        sa.UniqueConstraint(
            "season_id",
            "platform_transaction_id",
            name="uq_lv_tx_season_platform_id",
        ),
    )
    op.create_index(
        op.f("ix_lv_transactions_id"), "lv_transactions", ["id"], unique=False
    )

    op.create_table(
        "lv_draft_picks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("pick", sa.Integer(), nullable=False),
        sa.Column("overall_pick", sa.Integer(), nullable=True),
        sa.Column("platform_roster_id", sa.String(length=64), nullable=True),
        sa.Column("player_id", sa.String(length=64), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["draft_id"], ["lv_drafts.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["lv_teams.id"]),
    )
    op.create_index(
        op.f("ix_lv_draft_picks_id"), "lv_draft_picks", ["id"], unique=False
    )


def downgrade() -> None:
    op.drop_table("lv_draft_picks")
    op.drop_table("lv_transactions")
    op.drop_table("lv_records")
    op.drop_table("lv_matchups")
    op.drop_table("lv_drafts")
    op.drop_table("lv_teams")
    op.drop_table("lv_sync_jobs")
    op.drop_table("lv_seasons")
    op.drop_table("lv_managers")
    op.drop_table("lv_sites")
    op.drop_table("lv_league_lineage")
