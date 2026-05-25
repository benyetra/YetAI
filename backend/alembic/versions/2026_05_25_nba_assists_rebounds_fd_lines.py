"""Add FanDuel line columns to NBA assists/rebounds projections.

Revision ID: 20260525_nba_fd_core
Revises: 20260525_strikeout_mv
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260525_nba_fd_core"
down_revision = "20260525_strikeout_mv"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return column in {col["name"] for col in insp.get_columns(table)}


def _add_fd_columns(table: str) -> None:
    if not _has_column(table, "fanduel_line"):
        op.add_column(table, sa.Column("fanduel_line", sa.Float(), nullable=True))
    if not _has_column(table, "fanduel_over_under"):
        op.add_column(
            table,
            sa.Column("fanduel_over_under", sa.String(length=7), nullable=True),
        )


def upgrade() -> None:
    _add_fd_columns("pred_assists_projections")
    _add_fd_columns("pred_rebounds_projections")


def downgrade() -> None:
    for table in ("pred_assists_projections", "pred_rebounds_projections"):
        if _has_column(table, "fanduel_over_under"):
            op.drop_column(table, "fanduel_over_under")
        if _has_column(table, "fanduel_line"):
            op.drop_column(table, "fanduel_line")
