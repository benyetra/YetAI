"""Add features_used and model_version to NHL player SOG and team totals predictions."""

from alembic import op
import sqlalchemy as sa

revision = "2026_05_25_nhl_ml_shadow"
down_revision = "2026_05_24_nhl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pred_nhl_player_shots_predictions",
        sa.Column("model_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "pred_nhl_player_shots_predictions",
        sa.Column("features_used", sa.JSON(), nullable=True),
    )
    op.add_column(
        "pred_nhl_team_totals_predictions",
        sa.Column("model_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "pred_nhl_team_totals_predictions",
        sa.Column("features_used", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pred_nhl_team_totals_predictions", "features_used")
    op.drop_column("pred_nhl_team_totals_predictions", "model_version")
    op.drop_column("pred_nhl_player_shots_predictions", "features_used")
    op.drop_column("pred_nhl_player_shots_predictions", "model_version")
