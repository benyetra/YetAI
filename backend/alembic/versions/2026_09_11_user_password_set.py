"""Add password_set flag for Google-only accounts.

Revision ID: 20260911_password_set
Revises: 20260812_wnba_phase3_props
Create Date: 2026-09-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_password_set"
down_revision: Union[str, None] = "20260812_wnba_phase3_props"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "password_set",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "password_set")
