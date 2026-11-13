"""Auto-pick daily cap 4 -> 3 (data migration for the old default)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_auto_pick_cap_3"
down_revision: Union[str, None] = "20261110_nfl_recv_yds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "scoring_config",
        "max_picks_per_day",
        existing_type=sa.Integer(),
        server_default="3",
        existing_nullable=False,
    )
    op.execute(
        "UPDATE scoring_config SET max_picks_per_day = 3 WHERE max_picks_per_day = 4"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE scoring_config SET max_picks_per_day = 4 WHERE max_picks_per_day = 3"
    )
    op.alter_column(
        "scoring_config",
        "max_picks_per_day",
        existing_type=sa.Integer(),
        server_default="4",
        existing_nullable=False,
    )
