"""add unique constraint on pred_wnba_team_roster (team_id, player_id)

Revision ID: f8a2c91e04bd
Revises: e4d591511da1
Create Date: 2026-05-22

Dedupes duplicate roster rows before adding UNIQUE(team_id, player_id).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f8a2c91e04bd"
down_revision: Union[str, Sequence[str], None] = "e4d591511da1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM pred_wnba_team_roster a
        USING pred_wnba_team_roster b
        WHERE a.team_id = b.team_id
          AND a.player_id = b.player_id
          AND a.id > b.id
        """
    )
    op.create_unique_constraint(
        "unique_wnba_team_roster_team_player",
        "pred_wnba_team_roster",
        ["team_id", "player_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "unique_wnba_team_roster_team_player",
        "pred_wnba_team_roster",
        type_="unique",
    )
