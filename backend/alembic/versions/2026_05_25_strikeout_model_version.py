"""Add model_version to pred_strikeout_projections.

Revision ID: 20260525_strikeout_mv
Revises: 2026_05_24_nhl
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260525_strikeout_mv"
down_revision = "2026_05_24_nhl"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return column in {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column("pred_strikeout_projections", "model_version"):
        op.add_column(
            "pred_strikeout_projections",
            sa.Column("model_version", sa.String(length=20), nullable=True),
        )


def downgrade() -> None:
    if _has_column("pred_strikeout_projections", "model_version"):
        op.drop_column("pred_strikeout_projections", "model_version")
