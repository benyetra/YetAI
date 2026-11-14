"""pred_nba_prop_shadow: residual-model shadow predictions, graded in the model review (YetAI-g92)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_nba_prop_shadow"
down_revision: Union[str, None] = "20261114_recent_games_game_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "pred_nba_prop_shadow"
CONSTRAINT = "uq_nba_prop_shadow"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                player_id INTEGER NOT NULL,
                player_name VARCHAR(100),
                stat VARCHAR(16) NOT NULL,
                line DOUBLE PRECISION NOT NULL,
                line_source VARCHAR(64),
                over_price INTEGER,
                under_price INTEGER,
                best_over_price INTEGER,
                best_under_price INTEGER,
                pred_residual DOUBLE PRECISION NOT NULL,
                p_over DOUBLE PRECISION NOT NULL,
                model_version VARCHAR(64) NOT NULL,
                features JSON,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                CONSTRAINT {CONSTRAINT} UNIQUE (date, player_id, stat)
            )
            """
        )
        return
    if TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("player_id", sa.Integer, nullable=False),
        sa.Column("player_name", sa.String(100)),
        sa.Column("stat", sa.String(16), nullable=False),
        sa.Column("line", sa.Float, nullable=False),
        sa.Column("line_source", sa.String(64)),
        sa.Column("over_price", sa.Integer),
        sa.Column("under_price", sa.Integer),
        sa.Column("best_over_price", sa.Integer),
        sa.Column("best_under_price", sa.Integer),
        sa.Column("pred_residual", sa.Float, nullable=False),
        sa.Column("p_over", sa.Float, nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("features", sa.JSON),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
        sa.UniqueConstraint("date", "player_id", "stat", name=CONSTRAINT),
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
