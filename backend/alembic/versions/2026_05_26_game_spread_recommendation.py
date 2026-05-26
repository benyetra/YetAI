"""Add spread_recommendation to pred_game_projections."""

from alembic import op
import sqlalchemy as sa


revision = "2026_05_26_game_spread_rec"
down_revision = "20260525_game_mc"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column("pred_game_projections", "spread_recommendation"):
        op.add_column(
            "pred_game_projections",
            sa.Column("spread_recommendation", sa.String(length=20), nullable=True),
        )


def downgrade() -> None:
    if _has_column("pred_game_projections", "spread_recommendation"):
        op.drop_column("pred_game_projections", "spread_recommendation")
