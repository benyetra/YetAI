"""WNBA Phase 3 prop tables: three_pt_made + pra.

Revision ID: 20260812_wnba_phase3_props
Revises: 20260812_wnba_ml_gates
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_wnba_phase3_props"
down_revision: Union[str, None] = "20260812_wnba_ml_gates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROPS = ("three_pt_made", "pra")


def upgrade() -> None:
    for prop in _PROPS:
        proj = f"pred_wnba_{prop}_projections"
        act = f"pred_wnba_{prop}_actuals"
        op.create_table(
            proj,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("date", sa.Date(), nullable=False, index=True),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("player_name", sa.String(), nullable=True),
            sa.Column("opponent_team_name", sa.String(), nullable=True),
            sa.Column(f"projected_{prop}", sa.Float(), nullable=False),
            sa.Column("market_line", sa.Float(), nullable=True),
            sa.Column("edge", sa.Float(), nullable=True),
            sa.Column("recommendation", sa.String(length=20), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("news", sa.String(length=160), nullable=True),
            sa.Column("factors", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "player_id", "date", name=f"unique_wnba_{prop}_projection"
            ),
        )
        op.create_table(
            act,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("date", sa.Date(), nullable=False, index=True),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("player_name", sa.String(), nullable=True),
            sa.Column(f"actual_{prop}", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("player_id", "date", name=f"unique_wnba_{prop}_actual"),
        )


def downgrade() -> None:
    for prop in reversed(_PROPS):
        op.drop_table(f"pred_wnba_{prop}_actuals")
        op.drop_table(f"pred_wnba_{prop}_projections")
