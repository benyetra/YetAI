"""pred_recent_games.api_game_id + per-player unique; model_version on blocks / free throws (NBA-1)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_recent_games_game_id"
down_revision: Union[str, None] = "20261113_model_version_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "uq_recent_games_player_api_game"
VERSION_TABLES = ["pred_blocks_projections", "pred_free_throw_predictions"]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute(
            "ALTER TABLE pred_recent_games ADD COLUMN IF NOT EXISTS api_game_id INTEGER"
        )
        # Existing rows are all NULL, and NULLs never collide, so this cannot fail.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = '{CONSTRAINT}'
                ) THEN
                    ALTER TABLE pred_recent_games
                        ADD CONSTRAINT {CONSTRAINT} UNIQUE (player_id, api_game_id);
                END IF;
            END $$;
            """
        )
        for table in VERSION_TABLES:
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS model_version VARCHAR(64)"
            )
        return
    inspector = sa.inspect(bind)
    if "api_game_id" not in {
        c["name"] for c in inspector.get_columns("pred_recent_games")
    }:
        with op.batch_alter_table("pred_recent_games") as batch:
            batch.add_column(sa.Column("api_game_id", sa.Integer))
            batch.create_unique_constraint(CONSTRAINT, ["player_id", "api_game_id"])
    for table in VERSION_TABLES:
        if "model_version" not in {c["name"] for c in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("model_version", sa.String(64)))


def downgrade() -> None:
    op.execute(f"ALTER TABLE pred_recent_games DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute("ALTER TABLE pred_recent_games DROP COLUMN IF EXISTS api_game_id")
    for table in VERSION_TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS model_version")
