"""Multi-sport YetiWatch signals table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "20260630_yetiwatch_multisport"
down_revision = "20260629_yetiwatch"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    return inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has_table("pred_yetiwatch_signals"):
        op.create_table(
            "pred_yetiwatch_signals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sport", sa.String(16), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("as_of", sa.DateTime(), nullable=False),
            sa.Column("entity_id", sa.String(64), nullable=False),
            sa.Column("game_date", sa.Date(), nullable=False),
            sa.Column("game_id", sa.String(128), nullable=True),
            sa.Column("team_id", sa.String(64), nullable=True),
            sa.Column("opponent_id", sa.String(64), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("news_string", sa.String(160), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "sport",
                "entity_id",
                "game_date",
                name="unique_yetiwatch_entity_date",
            ),
        )
        op.create_index(
            "ix_pred_yetiwatch_signals_sport_date",
            "pred_yetiwatch_signals",
            ["sport", "game_date"],
        )
        op.create_index(
            "ix_pred_yetiwatch_signals_game_date",
            "pred_yetiwatch_signals",
            ["game_date"],
        )

    if _has_table("pred_wnba_yetiwatch_signals") and _has_table(
        "pred_yetiwatch_signals"
    ):
        bind = op.get_bind()
        bind.execute(
            text(
                """
                INSERT INTO pred_yetiwatch_signals (
                    sport, run_id, as_of, entity_id, game_date, game_id,
                    team_id, opponent_id, payload_json, news_string, created_at
                )
                SELECT
                    'wnba', run_id, as_of, player_id::text, game_date, game_id,
                    team_id::text, opponent_id::text, payload_json, news_string, created_at
                FROM pred_wnba_yetiwatch_signals w
                WHERE NOT EXISTS (
                    SELECT 1 FROM pred_yetiwatch_signals y
                    WHERE y.sport = 'wnba'
                      AND y.entity_id = w.player_id::text
                      AND y.game_date = w.game_date
                )
                """
            )
        )


def downgrade() -> None:
    if _has_table("pred_yetiwatch_signals"):
        op.drop_index(
            "ix_pred_yetiwatch_signals_game_date",
            table_name="pred_yetiwatch_signals",
        )
        op.drop_index(
            "ix_pred_yetiwatch_signals_sport_date",
            table_name="pred_yetiwatch_signals",
        )
        op.drop_table("pred_yetiwatch_signals")
