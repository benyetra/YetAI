"""odds_line_snapshots + best-price columns on NBA prop tables; blocks FanDuel line (X-3, X-4, NBA-9)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_odds_line_snapshots"
down_revision: Union[str, None] = "20261114_recent_games_game_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "odds_line_snapshots"
PROP_TABLES = [
    "pred_points_projections",
    "pred_three_point_projections",
    "pred_steals_projections",
    "pred_assists_projections",
    "pred_rebounds_projections",
    "pred_pra_projections",
    "pred_blocks_projections",
]
BEST_COLUMNS = [
    ("best_book", "VARCHAR(64)", sa.String(64)),
    ("best_line", "DOUBLE PRECISION", sa.Float),
    ("best_price", "INTEGER", sa.Integer),
    ("projected_at", "TIMESTAMP WITHOUT TIME ZONE", sa.DateTime),
]
BLOCKS_LINE_COLUMNS = [
    ("fanduel_line", "DOUBLE PRECISION", sa.Float),
    ("fanduel_over_under", "VARCHAR(7)", sa.String(7)),
    ("fanduel_price", "INTEGER", sa.Integer),
]


def _columns(table: str) -> list:
    cols = list(BEST_COLUMNS)
    if table == "pred_blocks_projections":
        cols += BLOCKS_LINE_COLUMNS
    return cols


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id BIGSERIAL PRIMARY KEY,
                sport VARCHAR(64) NOT NULL,
                event_id VARCHAR(64) NOT NULL,
                commence_time TIMESTAMP WITHOUT TIME ZONE,
                game_date DATE,
                home_team VARCHAR(100),
                away_team VARCHAR(100),
                market VARCHAR(64) NOT NULL,
                player_name VARCHAR(128),
                player_key VARCHAR(128) NOT NULL DEFAULT '',
                book VARCHAR(64) NOT NULL,
                line DOUBLE PRECISION,
                over_price INTEGER,
                under_price INTEGER,
                home_price INTEGER,
                away_price INTEGER,
                book_updated_at TIMESTAMP WITHOUT TIME ZONE,
                first_seen_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                last_seen_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
            )
            """
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_odds_snap_event "
            f"ON {TABLE} (event_id, market, book)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_odds_snap_lookup "
            f"ON {TABLE} (game_date, market, player_key)"
        )
        for table in PROP_TABLES:
            for name, pg_type, _ in _columns(table):
                op.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type}"
                )
        return

    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("sport", sa.String(64), nullable=False),
            sa.Column("event_id", sa.String(64), nullable=False),
            sa.Column("commence_time", sa.DateTime),
            sa.Column("game_date", sa.Date),
            sa.Column("home_team", sa.String(100)),
            sa.Column("away_team", sa.String(100)),
            sa.Column("market", sa.String(64), nullable=False),
            sa.Column("player_name", sa.String(128)),
            sa.Column("player_key", sa.String(128), nullable=False, server_default=""),
            sa.Column("book", sa.String(64), nullable=False),
            sa.Column("line", sa.Float),
            sa.Column("over_price", sa.Integer),
            sa.Column("under_price", sa.Integer),
            sa.Column("home_price", sa.Integer),
            sa.Column("away_price", sa.Integer),
            sa.Column("book_updated_at", sa.DateTime),
            sa.Column("first_seen_at", sa.DateTime, nullable=False),
            sa.Column("last_seen_at", sa.DateTime, nullable=False),
        )
        op.create_index("ix_odds_snap_event", TABLE, ["event_id", "market", "book"])
        op.create_index(
            "ix_odds_snap_lookup", TABLE, ["game_date", "market", "player_key"]
        )
    for table in PROP_TABLES:
        have = {c["name"] for c in inspector.get_columns(table)}
        for name, _, sa_type in _columns(table):
            if name not in have:
                op.add_column(table, sa.Column(name, sa_type))


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
    for table in PROP_TABLES:
        for name, _, _ in _columns(table):
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {name}")
