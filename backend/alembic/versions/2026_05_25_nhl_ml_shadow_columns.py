"""Add features_used and model_version to NHL player SOG and team totals predictions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "2026_05_25_nhl_ml_shadow"
down_revision = "2026_05_24_nhl"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return column in {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    if not _has_column("pred_nhl_player_shots_predictions", "model_version"):
        op.add_column(
            "pred_nhl_player_shots_predictions",
            sa.Column("model_version", sa.String(length=20), nullable=True),
        )
    if not _has_column("pred_nhl_player_shots_predictions", "features_used"):
        op.add_column(
            "pred_nhl_player_shots_predictions",
            sa.Column("features_used", sa.JSON(), nullable=True),
        )
    if not _has_column("pred_nhl_team_totals_predictions", "model_version"):
        op.add_column(
            "pred_nhl_team_totals_predictions",
            sa.Column("model_version", sa.String(length=20), nullable=True),
        )
    if not _has_column("pred_nhl_team_totals_predictions", "features_used"):
        op.add_column(
            "pred_nhl_team_totals_predictions",
            sa.Column("features_used", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("pred_nhl_team_totals_predictions", "features_used"):
        op.drop_column("pred_nhl_team_totals_predictions", "features_used")
    if _has_column("pred_nhl_team_totals_predictions", "model_version"):
        op.drop_column("pred_nhl_team_totals_predictions", "model_version")
    if _has_column("pred_nhl_player_shots_predictions", "features_used"):
        op.drop_column("pred_nhl_player_shots_predictions", "features_used")
    if _has_column("pred_nhl_player_shots_predictions", "model_version"):
        op.drop_column("pred_nhl_player_shots_predictions", "model_version")
