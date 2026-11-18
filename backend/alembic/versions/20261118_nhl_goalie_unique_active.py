"""one live NHL goalie prediction per (game_date, team_id)

Revision ID: 20261118_nhl_goalie_uq
Revises: 20261118_nba_prop_low_sample
Create Date: 2026-11-18

Removes duplicate live rows (keeps the latest id per game_date + team_id), then adds a
partial unique index. Rows flagged was_scratch are superseded starters kept for history,
so they are outside the key.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20261118_nhl_goalie_uq"
down_revision: Union[str, None] = "20261118_nba_prop_low_sample"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = "uq_nhl_goalie_pred_date_team_active"
TABLE = "pred_nhl_goalie_predictions"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Fail fast (the deploy aborts, safe to re-run) if an NHL run holds the table.
        op.execute("SET LOCAL lock_timeout = '5s'")
    # Same rule on Postgres and SQLite: per (game_date, team_id), keep the newest live row.
    op.execute(
        f"""
        DELETE FROM {TABLE}
        WHERE was_scratch IS NOT TRUE
          AND id NOT IN (
            SELECT MAX(id) FROM {TABLE}
            WHERE was_scratch IS NOT TRUE
            GROUP BY game_date, team_id
          )
        """
    )
    op.create_index(
        INDEX,
        TABLE,
        ["game_date", "team_id"],
        unique=True,
        postgresql_where=sa.text("was_scratch IS NOT TRUE"),
        sqlite_where=sa.text("was_scratch IS NOT 1"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
