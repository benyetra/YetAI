"""auto_yetai_picks: pending status, scoring fields, runs+config tables

Revision ID: 186bd4461744
Revises: c3b8a1f92d04
Create Date: 2026-05-22 14:33:07.357517

"""
from datetime import datetime as _dt
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "186bd4461744"
down_revision: Union[str, None] = "c3b8a1f92d04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return column in {col["name"] for col in insp.get_columns(table)}


def _has_index(table: str, index_name: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return index_name in {idx["name"] for idx in insp.get_indexes(table)}


def _enum_type_exists(conn, typname: str) -> bool:
    return conn.execute(
        text(
            "SELECT 1 FROM pg_type WHERE typname = :n AND typtype = 'e'"
        ),
        {"n": typname},
    ).fetchone() is not None


def _enum_value_exists(conn, typname: str, value: str) -> bool:
    return conn.execute(
        text(
            "SELECT 1 FROM pg_enum e "
            "JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = :n AND e.enumlabel = :v"
        ),
        {"n": typname, "v": value},
    ).fetchone() is not None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Ensure PostgreSQL enum types exist BEFORE any table/column
    #    references them. All done via raw SQL to avoid SQLAlchemy's
    #    automatic type-creation side effects in op.create_table.
    # ------------------------------------------------------------------

    if not _enum_type_exists(conn, "betsource"):
        conn.execute(
            text("CREATE TYPE betsource AS ENUM ('manual', 'auto')")
        )

    if not _enum_type_exists(conn, "autopickrunstatus"):
        conn.execute(
            text(
                "CREATE TYPE autopickrunstatus AS ENUM "
                "('success', 'partial', 'failed', 'no_picks')"
            )
        )

    # Extend betstatus with new values. ADD VALUE IF NOT EXISTS is Postgres 9.6+.
    for val in ("pending_approval", "rejected", "expired"):
        if not _enum_value_exists(conn, "betstatus", val):
            conn.execute(
                text(f"ALTER TYPE betstatus ADD VALUE IF NOT EXISTS '{val}'")
            )

    # ------------------------------------------------------------------
    # 2. Create auto_pick_runs table via raw SQL to avoid SQLAlchemy
    #    automatically re-creating the autopickrunstatus enum type.
    # ------------------------------------------------------------------
    if not _has_table("auto_pick_runs"):
        conn.execute(
            text(
                """
                CREATE TABLE auto_pick_runs (
                    id                   SERIAL PRIMARY KEY,
                    run_at               TIMESTAMP NOT NULL,
                    status               autopickrunstatus NOT NULL,
                    candidates_considered INTEGER NOT NULL DEFAULT 0,
                    candidates_selected   INTEGER NOT NULL DEFAULT 0,
                    dropped_reasons       JSONB,
                    error                 TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE INDEX idx_auto_pick_runs_run_at ON auto_pick_runs (run_at)"
            )
        )

    # ------------------------------------------------------------------
    # 3. Create scoring_config table
    # ------------------------------------------------------------------
    if not _has_table("scoring_config"):
        op.create_table(
            "scoring_config",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "weight_edge", sa.Float(), nullable=False, server_default="0.40"
            ),
            sa.Column(
                "weight_historical", sa.Float(), nullable=False, server_default="0.20"
            ),
            sa.Column(
                "weight_freshness", sa.Float(), nullable=False, server_default="0.15"
            ),
            sa.Column(
                "weight_line_movement",
                sa.Float(),
                nullable=False,
                server_default="0.10",
            ),
            sa.Column(
                "weight_odds_sanity",
                sa.Float(),
                nullable=False,
                server_default="0.10",
            ),
            sa.Column(
                "weight_model_conf", sa.Float(), nullable=False, server_default="0.05"
            ),
            sa.Column(
                "score_threshold", sa.Float(), nullable=False, server_default="65.0"
            ),
            sa.Column(
                "odds_min", sa.Integer(), nullable=False, server_default="-300"
            ),
            sa.Column(
                "odds_max", sa.Integer(), nullable=False, server_default="400"
            ),
            sa.Column(
                "max_picks_per_day", sa.Integer(), nullable=False, server_default="4"
            ),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    # ------------------------------------------------------------------
    # 4. Add new columns to yetai_bets via raw SQL for enum columns
    #    to avoid duplicate-type errors.
    # ------------------------------------------------------------------
    if not _has_column("yetai_bets", "confidence_score"):
        op.add_column(
            "yetai_bets",
            sa.Column("confidence_score", sa.Float(), nullable=True),
        )

    if not _has_column("yetai_bets", "score_breakdown"):
        op.add_column(
            "yetai_bets",
            sa.Column("score_breakdown", JSONB(), nullable=True),
        )

    if not _has_column("yetai_bets", "reasoning"):
        op.add_column(
            "yetai_bets",
            sa.Column("reasoning", sa.Text(), nullable=True),
        )

    if not _has_column("yetai_bets", "source"):
        conn.execute(
            text(
                "ALTER TABLE yetai_bets "
                "ADD COLUMN source betsource NOT NULL DEFAULT 'manual'"
            )
        )

    if not _has_column("yetai_bets", "auto_pick_run_id"):
        conn.execute(
            text(
                "ALTER TABLE yetai_bets "
                "ADD COLUMN auto_pick_run_id INTEGER "
                "REFERENCES auto_pick_runs(id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX idx_yetai_bets_auto_pick_run_id "
                "ON yetai_bets (auto_pick_run_id)"
            )
        )

    # ------------------------------------------------------------------
    # 5. Seed a single default row in scoring_config
    # ------------------------------------------------------------------
    row_count = conn.execute(
        text("SELECT COUNT(*) FROM scoring_config")
    ).scalar()
    if row_count == 0:
        conn.execute(
            text(
                "INSERT INTO scoring_config "
                "(weight_edge, weight_historical, weight_freshness, "
                "weight_line_movement, weight_odds_sanity, weight_model_conf, "
                "score_threshold, odds_min, odds_max, max_picks_per_day, updated_at) "
                "VALUES "
                "(0.40, 0.20, 0.15, 0.10, 0.10, 0.05, 65.0, -300, 400, 4, :now)"
            ),
            {"now": _dt.utcnow()},
        )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()

    # Drop new columns from yetai_bets (reverse order)
    if _has_index("yetai_bets", "idx_yetai_bets_auto_pick_run_id"):
        op.drop_index("idx_yetai_bets_auto_pick_run_id", table_name="yetai_bets")
    if _has_column("yetai_bets", "auto_pick_run_id"):
        op.drop_column("yetai_bets", "auto_pick_run_id")
    if _has_column("yetai_bets", "source"):
        op.drop_column("yetai_bets", "source")
    if _has_column("yetai_bets", "reasoning"):
        op.drop_column("yetai_bets", "reasoning")
    if _has_column("yetai_bets", "score_breakdown"):
        op.drop_column("yetai_bets", "score_breakdown")
    if _has_column("yetai_bets", "confidence_score"):
        op.drop_column("yetai_bets", "confidence_score")

    # Drop new tables
    if _has_index("auto_pick_runs", "idx_auto_pick_runs_run_at"):
        op.drop_index("idx_auto_pick_runs_run_at", table_name="auto_pick_runs")
    if _has_table("scoring_config"):
        op.drop_table("scoring_config")
    if _has_table("auto_pick_runs"):
        op.drop_table("auto_pick_runs")

    # Drop enum types created in upgrade
    conn.execute(text("DROP TYPE IF EXISTS betsource"))
    conn.execute(text("DROP TYPE IF EXISTS autopickrunstatus"))

    # NOTE: The three values added to 'betstatus' (pending_approval, rejected, expired)
    # cannot be removed — PostgreSQL does not support removing enum values.
