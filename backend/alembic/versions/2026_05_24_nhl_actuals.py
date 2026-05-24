"""nhl team shots / player shots / team totals actuals

Adds three actuals tables for NHL predictions whose ETL writers are new
in this PR. Mirrors the goalie-actuals pattern so the accuracy service
can grade O/U calls and compute MAE without a JOIN against predictions.

Revision ID: 2026_05_24_nhl
Revises: 20260524_strikeout_pick
Create Date: 2026-05-24 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2026_05_24_nhl"
down_revision: Union[str, Sequence[str], None] = "20260524_strikeout_pick"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "pred_nhl_team_shots_actuals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("team_name", sa.String(length=100), nullable=False),
        sa.Column("opponent_team_id", sa.Integer()),
        sa.Column("opponent_team_name", sa.String(length=100)),
        sa.Column("actual_shots", sa.Integer(), nullable=False),
        sa.Column("predicted_shots", sa.Float()),
        sa.Column("shots_line", sa.Float()),
        sa.Column("betting_recommendation", sa.String(length=20)),
        sa.Column("recommendation_correct", sa.Boolean()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_pred_nhl_team_shots_actuals_game_id",
        "pred_nhl_team_shots_actuals",
        ["game_id"],
    )
    op.create_index(
        "ix_pred_nhl_team_shots_actuals_game_date",
        "pred_nhl_team_shots_actuals",
        ["game_date"],
    )

    op.create_table(
        "pred_nhl_player_shots_actuals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(length=100), nullable=False),
        sa.Column("team_name", sa.String(length=100), nullable=False),
        sa.Column("opponent_team_name", sa.String(length=100)),
        sa.Column("actual_shots", sa.Integer(), nullable=False),
        sa.Column("predicted_shots", sa.Float()),
        sa.Column("shots_line", sa.Float()),
        sa.Column("betting_recommendation", sa.String(length=20)),
        sa.Column("recommendation_correct", sa.Boolean()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_pred_nhl_player_shots_actuals_game_id",
        "pred_nhl_player_shots_actuals",
        ["game_id"],
    )
    op.create_index(
        "ix_pred_nhl_player_shots_actuals_game_date",
        "pred_nhl_player_shots_actuals",
        ["game_date"],
    )
    op.create_index(
        "ix_pred_nhl_player_shots_actuals_player_id",
        "pred_nhl_player_shots_actuals",
        ["player_id"],
    )

    op.create_table(
        "pred_nhl_team_totals_actuals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("home_team_id", sa.Integer(), nullable=False),
        sa.Column("home_team_name", sa.String(length=100), nullable=False),
        sa.Column("away_team_id", sa.Integer(), nullable=False),
        sa.Column("away_team_name", sa.String(length=100), nullable=False),
        sa.Column("actual_home_goals", sa.Integer(), nullable=False),
        sa.Column("actual_away_goals", sa.Integer(), nullable=False),
        sa.Column("actual_total_goals", sa.Integer(), nullable=False),
        sa.Column("predicted_total_goals", sa.Float()),
        sa.Column("draftkings_ou_line", sa.Float()),
        sa.Column("betting_recommendation", sa.String(length=20)),
        sa.Column("recommendation_correct", sa.Boolean()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_pred_nhl_team_totals_actuals_game_date",
        "pred_nhl_team_totals_actuals",
        ["game_date"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_pred_nhl_team_totals_actuals_game_date",
        table_name="pred_nhl_team_totals_actuals",
    )
    op.drop_table("pred_nhl_team_totals_actuals")

    op.drop_index(
        "ix_pred_nhl_player_shots_actuals_player_id",
        table_name="pred_nhl_player_shots_actuals",
    )
    op.drop_index(
        "ix_pred_nhl_player_shots_actuals_game_date",
        table_name="pred_nhl_player_shots_actuals",
    )
    op.drop_index(
        "ix_pred_nhl_player_shots_actuals_game_id",
        table_name="pred_nhl_player_shots_actuals",
    )
    op.drop_table("pred_nhl_player_shots_actuals")

    op.drop_index(
        "ix_pred_nhl_team_shots_actuals_game_date",
        table_name="pred_nhl_team_shots_actuals",
    )
    op.drop_index(
        "ix_pred_nhl_team_shots_actuals_game_id",
        table_name="pred_nhl_team_shots_actuals",
    )
    op.drop_table("pred_nhl_team_shots_actuals")
