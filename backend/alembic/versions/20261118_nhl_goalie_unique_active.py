"""one live NHL goalie prediction per (game_date, team_id)

Revision ID: 20261118_nhl_goalie_uq
Revises: 20261115_fair_price_shadow
Create Date: 2026-11-18

Removes duplicate live rows (keeps the latest id per game_date + team_id), then adds a
partial unique index. Rows flagged was_scratch are superseded starters kept for history,
so they are outside the key.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20261118_nhl_goalie_uq"
down_revision: Union[str, None] = "20261115_fair_price_shadow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = "uq_nhl_goalie_pred_date_team_active"
TABLE = "pred_nhl_goalie_predictions"


def upgrade() -> None:
    op.execute(
        f"""
        DELETE FROM {TABLE} a
        USING {TABLE} b
        WHERE a.game_date = b.game_date
          AND a.team_id = b.team_id
          AND a.was_scratch IS NOT TRUE
          AND b.was_scratch IS NOT TRUE
          AND a.id < b.id
        """
    )
    op.create_index(
        INDEX,
        TABLE,
        ["game_date", "team_id"],
        unique=True,
        postgresql_where="was_scratch IS NOT TRUE",
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
