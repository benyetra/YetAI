"""best_fair_prob / best_ev on NBA prop tables: consensus fair probability and EV of the best price."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_prop_best_fair_ev"
down_revision: Union[str, None] = "20261115_fair_price_shadow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROP_TABLES = [
    "pred_points_projections",
    "pred_three_point_projections",
    "pred_steals_projections",
    "pred_assists_projections",
    "pred_rebounds_projections",
    "pred_pra_projections",
    "pred_blocks_projections",
]
COLUMNS = [
    ("best_fair_prob", "DOUBLE PRECISION", sa.Float),
    ("best_ev", "DOUBLE PRECISION", sa.Float),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        for table in PROP_TABLES:
            for name, pg_type, _ in COLUMNS:
                op.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type}"
                )
        return

    inspector = sa.inspect(bind)
    for table in PROP_TABLES:
        have = {c["name"] for c in inspector.get_columns(table)}
        for name, _, sa_type in COLUMNS:
            if name not in have:
                op.add_column(table, sa.Column(name, sa_type))


def downgrade() -> None:
    for table in PROP_TABLES:
        for name, _, _ in COLUMNS:
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {name}")
