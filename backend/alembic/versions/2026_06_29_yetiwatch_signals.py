"""YetiWatch signals table and news column on WNBA prop projections."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260629_yetiwatch"
down_revision = "20260610_yetai_hits"
branch_labels = None
depends_on = None

_PROP_TABLES = (
    "pred_wnba_points_projections",
    "pred_wnba_assists_projections",
    "pred_wnba_rebounds_projections",
)


def _has_table(table: str) -> bool:
    return inspect(op.get_bind()).has_table(table)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_table("pred_wnba_yetiwatch_signals"):
        op.create_table(
            "pred_wnba_yetiwatch_signals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("as_of", sa.DateTime(), nullable=False),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("game_id", sa.String(128), nullable=True),
            sa.Column("team_id", sa.Integer(), nullable=True),
            sa.Column("opponent_id", sa.Integer(), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("news_string", sa.String(160), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "player_id",
                "game_date",
                name="unique_wnba_yetiwatch_player_date",
            ),
        )
        op.create_index(
            "ix_pred_wnba_yetiwatch_signals_game_date",
            "pred_wnba_yetiwatch_signals",
            ["game_date"],
        )

    for table in _PROP_TABLES:
        if _has_table(table) and not _has_column(table, "news"):
            op.add_column(table, sa.Column("news", sa.String(160), nullable=True))


def downgrade() -> None:
    for table in _PROP_TABLES:
        if _has_column(table, "news"):
            op.drop_column(table, "news")
    if _has_table("pred_wnba_yetiwatch_signals"):
        op.drop_table("pred_wnba_yetiwatch_signals")
