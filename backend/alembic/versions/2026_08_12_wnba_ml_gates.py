"""WNBA prop factors JSON + totals accuracy heuristic/ml MAE columns.

Revision ID: 20260812_wnba_ml_gates
Revises: 20260811_atd_model_ver
Create Date: 2026-08-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_wnba_ml_gates"
down_revision: Union[str, None] = "20260811_atd_model_ver"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROP_TABLES = (
    "pred_wnba_points_projections",
    "pred_wnba_assists_projections",
    "pred_wnba_rebounds_projections",
)


def upgrade() -> None:
    for table in _PROP_TABLES:
        op.add_column(
            table,
            sa.Column("factors", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        )
    op.add_column(
        "pred_wnba_totals_accuracy",
        sa.Column("heuristic_mean_absolute_error", sa.Float(), nullable=True),
    )
    op.add_column(
        "pred_wnba_totals_accuracy",
        sa.Column("ml_mean_absolute_error", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pred_wnba_totals_accuracy", "ml_mean_absolute_error")
    op.drop_column("pred_wnba_totals_accuracy", "heuristic_mean_absolute_error")
    for table in _PROP_TABLES:
        op.drop_column(table, "factors")
