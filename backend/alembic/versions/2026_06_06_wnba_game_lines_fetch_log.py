"""WNBA historical game lines fetch-once log.

Revision ID: 20260606_wnba_fetch_log
Revises: 20260604_ps_beat_key
Create Date: 2026-06-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_wnba_fetch_log"
down_revision: Union[str, None] = "20260604_ps_beat_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pred_wnba_game_lines_fetch_log",
        sa.Column("fetch_date", sa.Date(), nullable=False),
        sa.Column("events_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="api"),
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("fetch_date"),
    )


def downgrade() -> None:
    op.drop_table("pred_wnba_game_lines_fetch_log")
