"""add_expected_minutes_to_pred_wnba_today_active_players

Revision ID: e4d591511da1
Revises: 0107ad42b713
Create Date: 2026-05-22 06:25:51.831414

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4d591511da1'
down_revision: Union[str, Sequence[str], None] = '0107ad42b713'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("pred_wnba_today_active_players", sa.Column("expected_minutes", sa.Float, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("pred_wnba_today_active_players", "expected_minutes")
