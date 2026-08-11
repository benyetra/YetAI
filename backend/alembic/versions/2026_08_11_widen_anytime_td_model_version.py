"""Widen pred_nfl_anytime_td_predictions.model_version to varchar(64).

``hierarchical_v1_gbm_pos`` is 23 chars and truncates under the original
varchar(20), failing celery upserts with StringDataRightTruncation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260811_atd_model_ver"
down_revision: Union[str, None] = "20260810_nfl_anytime_td"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("pred_nfl_anytime_td_predictions"):
        return
    op.alter_column(
        "pred_nfl_anytime_td_predictions",
        "model_version",
        existing_type=sa.String(20),
        type_=sa.String(64),
        existing_nullable=True,
    )


def downgrade() -> None:
    if not _has_table("pred_nfl_anytime_td_predictions"):
        return
    op.alter_column(
        "pred_nfl_anytime_td_predictions",
        "model_version",
        existing_type=sa.String(64),
        type_=sa.String(20),
        existing_nullable=True,
    )
