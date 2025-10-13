"""Add broadcast_info and is_nationally_televised to Game model

Revision ID: a1b2c3d4e5f6
Revises: 93bbff37008d
Create Date: 2025-10-13 16:50:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "93bbff37008d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add broadcast_info column (JSON) to games table
    op.add_column(
        "games",
        sa.Column("broadcast_info", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )

    # Add is_nationally_televised column (Boolean) to games table
    op.add_column(
        "games",
        sa.Column("is_nationally_televised", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove columns from games table
    op.drop_column("games", "is_nationally_televised")
    op.drop_column("games", "broadcast_info")
