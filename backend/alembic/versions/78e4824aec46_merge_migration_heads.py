"""Merge migration heads

Revision ID: 78e4824aec46
Revises: 6f9432b1809e, sleeper_sync_manual
Create Date: 2025-10-12 13:39:50.260030

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "78e4824aec46"
down_revision: Union[str, Sequence[str], None] = ("6f9432b1809e", "sleeper_sync_manual")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
