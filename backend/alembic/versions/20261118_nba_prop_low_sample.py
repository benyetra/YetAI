"""low_sample on the NBA pickable prop tables: player has < 5 current-season games."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_nba_prop_low_sample"
down_revision: Union[str, None] = "20261115_fair_price_shadow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "pred_points_projections",
    "pred_rebounds_projections",
    "pred_assists_projections",
    "pred_three_point_projections",
    "pred_steals_projections",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Fail fast if a running pipeline holds a table; safe to re-run.
        op.execute("SET LOCAL lock_timeout = '5s'")
        for table in TABLES:
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS low_sample BOOLEAN"
            )
        return
    inspector = sa.inspect(bind)
    for table in TABLES:
        if "low_sample" not in {c["name"] for c in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("low_sample", sa.Boolean()))


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS low_sample")
