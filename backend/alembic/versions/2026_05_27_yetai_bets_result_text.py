"""Widen yetai_bets.result for settlement notes.

Revision ID: 20260527_yetai_result
Revises: 20260526_mlb_archetypes
Create Date: 2026-05-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260527_yetai_result"
down_revision: Union[str, None] = "20260526_mlb_archetypes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "yetai_bets",
        "result",
        existing_type=sa.String(length=50),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "yetai_bets",
        "result",
        existing_type=sa.Text(),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
