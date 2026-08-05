"""Add matchup_source to pred_pitcher and pred_strikeout_projections.

Revision ID: 20260805_k_matchup_src
Revises: 20260630_yetiwatch_multisport
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260805_k_matchup_src"
down_revision = "20260630_yetiwatch_multisport"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return column in {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column("pred_pitcher", "matchup_source"):
        op.add_column(
            "pred_pitcher",
            sa.Column("matchup_source", sa.String(length=16), nullable=True),
        )
    if not _has_column("pred_strikeout_projections", "matchup_source"):
        op.add_column(
            "pred_strikeout_projections",
            sa.Column("matchup_source", sa.String(length=16), nullable=True),
        )


def downgrade() -> None:
    if _has_column("pred_strikeout_projections", "matchup_source"):
        op.drop_column("pred_strikeout_projections", "matchup_source")
    if _has_column("pred_pitcher", "matchup_source"):
        op.drop_column("pred_pitcher", "matchup_source")
