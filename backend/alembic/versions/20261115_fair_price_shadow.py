"""fair_price_shadow_flags + fair_price_weights: fair-price shadow flags and fitted weights."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261115_fair_price_shadow"
down_revision: Union[str, None] = "20261114_nba_prop_shadow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FLAGS = "fair_price_shadow_flags"
WEIGHTS = "fair_price_weights"
FLAGS_UQ = "uq_fair_price_shadow_flag"
WEIGHTS_UQ = "uq_fair_price_weights"
INDEX = "ix_fp_shadow_game_date"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {FLAGS} (
                id BIGSERIAL PRIMARY KEY,
                rule_version VARCHAR(64) NOT NULL,
                engine_version VARCHAR(64) NOT NULL,
                tier VARCHAR(16) NOT NULL,
                sport VARCHAR(64) NOT NULL,
                event_id VARCHAR(64) NOT NULL,
                game_date DATE,
                commence_time TIMESTAMP,
                market VARCHAR(64) NOT NULL,
                player_key VARCHAR(128) NOT NULL,
                player_name VARCHAR(128),
                side VARCHAR(1) NOT NULL,
                book VARCHAR(64) NOT NULL,
                line DOUBLE PRECISION NOT NULL,
                price INTEGER NOT NULL,
                book_updated_at TIMESTAMP,
                observed_at TIMESTAMP NOT NULL,
                flagged_at TIMESTAMP NOT NULL,
                quote_age_min DOUBLE PRECISION,
                hours_before DOUBLE PRECISION,
                fair_prob DOUBLE PRECISION NOT NULL,
                ev DOUBLE PRECISION NOT NULL,
                playable_to INTEGER NOT NULL,
                n_books INTEGER NOT NULL,
                devig_method VARCHAR(16) NOT NULL,
                weights_version VARCHAR(64) NOT NULL,
                consensus JSON,
                last_qualified_at TIMESTAMP NOT NULL,
                last_line DOUBLE PRECISION,
                last_price INTEGER,
                n_qualified INTEGER NOT NULL DEFAULT 1,
                graded_at TIMESTAMP,
                is_close BOOLEAN,
                close_at TIMESTAMP,
                close_prob DOUBLE PRECISION,
                n_close INTEGER,
                clv DOUBLE PRECISION,
                close_note VARCHAR(32),
                actual DOUBLE PRECISION,
                result VARCHAR(16),
                units DOUBLE PRECISION,
                next_at TIMESTAMP,
                next_price INTEGER,
                next_playable BOOLEAN,
                baseline JSON,
                created_at TIMESTAMP,
                CONSTRAINT {FLAGS_UQ} UNIQUE (
                    rule_version, event_id, market, player_key, side, book
                )
            )
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON {FLAGS} (game_date)")
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {WEIGHTS} (
                id SERIAL PRIMARY KEY,
                version VARCHAR(64) NOT NULL,
                sport VARCHAR(64) NOT NULL,
                market VARCHAR(64) NOT NULL,
                weights JSON NOT NULL,
                fitted JSON,
                n_rows INTEGER,
                fitted_through DATE,
                source VARCHAR(64),
                created_at TIMESTAMP,
                CONSTRAINT {WEIGHTS_UQ} UNIQUE (version, sport, market)
            )
            """
        )
        return
    have = set(sa.inspect(bind).get_table_names())
    if FLAGS not in have:
        op.create_table(
            FLAGS,
            sa.Column(
                "id",
                sa.BigInteger().with_variant(sa.Integer, "sqlite"),
                primary_key=True,
            ),
            sa.Column("rule_version", sa.String(64), nullable=False),
            sa.Column("engine_version", sa.String(64), nullable=False),
            sa.Column("tier", sa.String(16), nullable=False),
            sa.Column("sport", sa.String(64), nullable=False),
            sa.Column("event_id", sa.String(64), nullable=False),
            sa.Column("game_date", sa.Date),
            sa.Column("commence_time", sa.DateTime),
            sa.Column("market", sa.String(64), nullable=False),
            sa.Column("player_key", sa.String(128), nullable=False),
            sa.Column("player_name", sa.String(128)),
            sa.Column("side", sa.String(1), nullable=False),
            sa.Column("book", sa.String(64), nullable=False),
            sa.Column("line", sa.Float, nullable=False),
            sa.Column("price", sa.Integer, nullable=False),
            sa.Column("book_updated_at", sa.DateTime),
            sa.Column("observed_at", sa.DateTime, nullable=False),
            sa.Column("flagged_at", sa.DateTime, nullable=False),
            sa.Column("quote_age_min", sa.Float),
            sa.Column("hours_before", sa.Float),
            sa.Column("fair_prob", sa.Float, nullable=False),
            sa.Column("ev", sa.Float, nullable=False),
            sa.Column("playable_to", sa.Integer, nullable=False),
            sa.Column("n_books", sa.Integer, nullable=False),
            sa.Column("devig_method", sa.String(16), nullable=False),
            sa.Column("weights_version", sa.String(64), nullable=False),
            sa.Column("consensus", sa.JSON),
            sa.Column("last_qualified_at", sa.DateTime, nullable=False),
            sa.Column("last_line", sa.Float),
            sa.Column("last_price", sa.Integer),
            sa.Column("n_qualified", sa.Integer, nullable=False, server_default="1"),
            sa.Column("graded_at", sa.DateTime),
            sa.Column("is_close", sa.Boolean),
            sa.Column("close_at", sa.DateTime),
            sa.Column("close_prob", sa.Float),
            sa.Column("n_close", sa.Integer),
            sa.Column("clv", sa.Float),
            sa.Column("close_note", sa.String(32)),
            sa.Column("actual", sa.Float),
            sa.Column("result", sa.String(16)),
            sa.Column("units", sa.Float),
            sa.Column("next_at", sa.DateTime),
            sa.Column("next_price", sa.Integer),
            sa.Column("next_playable", sa.Boolean),
            sa.Column("baseline", sa.JSON),
            sa.Column("created_at", sa.DateTime),
            sa.UniqueConstraint(
                "rule_version",
                "event_id",
                "market",
                "player_key",
                "side",
                "book",
                name=FLAGS_UQ,
            ),
        )
        op.create_index(INDEX, FLAGS, ["game_date"])
    if WEIGHTS not in have:
        op.create_table(
            WEIGHTS,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("version", sa.String(64), nullable=False),
            sa.Column("sport", sa.String(64), nullable=False),
            sa.Column("market", sa.String(64), nullable=False),
            sa.Column("weights", sa.JSON, nullable=False),
            sa.Column("fitted", sa.JSON),
            sa.Column("n_rows", sa.Integer),
            sa.Column("fitted_through", sa.Date),
            sa.Column("source", sa.String(64)),
            sa.Column("created_at", sa.DateTime),
            sa.UniqueConstraint("version", "sport", "market", name=WEIGHTS_UQ),
        )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {WEIGHTS}")
    op.execute(f"DROP TABLE IF EXISTS {FLAGS}")
