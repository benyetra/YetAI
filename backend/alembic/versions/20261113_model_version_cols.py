"""Persist model_version on every projection table (L3)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_model_version_cols"
down_revision: Union[str, None] = "20261113_prop_fanduel_price"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "pred_kickers",
    "pred_nfl_spread_projections",
    "pred_nfl_totals_projections",
    "pred_points_projections",
    "pred_three_point_projections",
    "pred_steals_projections",
    "pred_assists_projections",
    "pred_rebounds_projections",
    "pred_pra_projections",
    "pred_nba_totals_projections",
    "pred_nba_spread_projections",
    "pred_nhl_team_shots_predictions",
    "pred_wnba_totals_projections",
    "pred_wnba_spread_projections",
    "pred_wnba_points_projections",
    "pred_wnba_assists_projections",
    "pred_wnba_rebounds_projections",
    "pred_wnba_three_pt_made_projections",
    "pred_wnba_pra_projections",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Fail fast if a running pipeline holds one of the tables, so the tables
        # already altered in this transaction are not left locked; safe to re-run.
        op.execute("SET LOCAL lock_timeout = '5s'")
        for table in TABLES:
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS model_version VARCHAR(20)"
            )
        return
    inspector = sa.inspect(bind)
    for table in TABLES:
        if "model_version" not in {c["name"] for c in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("model_version", sa.String(20)))


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS model_version")
