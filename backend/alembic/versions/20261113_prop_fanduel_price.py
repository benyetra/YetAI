"""Store the FanDuel price (American odds of the picked side) on NBA/WNBA prop tables."""

from typing import Sequence, Union

from alembic import op

revision: str = "20261113_prop_fanduel_price"
down_revision: Union[str, None] = "20261113_auto_pick_cap_3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "pred_points_projections",
    "pred_three_point_projections",
    "pred_steals_projections",
    "pred_assists_projections",
    "pred_rebounds_projections",
    "pred_pra_projections",
    "pred_wnba_points_projections",
    "pred_wnba_assists_projections",
    "pred_wnba_rebounds_projections",
    "pred_wnba_three_pt_made_projections",
    "pred_wnba_pra_projections",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS fanduel_price INTEGER"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS fanduel_price")
