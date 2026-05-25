"""Add sim_distribution JSON to pred_game_projections for Monte Carlo outputs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260525_game_mc"
down_revision = "466f48ac4605"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return column in {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column("pred_game_projections", "sim_distribution"):
        op.add_column(
            "pred_game_projections",
            sa.Column("sim_distribution", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("pred_game_projections", "sim_distribution"):
        op.drop_column("pred_game_projections", "sim_distribution")
