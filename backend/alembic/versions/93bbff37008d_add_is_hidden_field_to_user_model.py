"""Add is_hidden field to User model

Revision ID: 93bbff37008d
Revises: 78e4824aec46
Create Date: 2025-10-12 13:40:04.135243

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "93bbff37008d"
down_revision: Union[str, Sequence[str], None] = "78e4824aec46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add is_hidden column to users table
    op.add_column(
        "users",
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove is_hidden column from users table
    op.drop_column("users", "is_hidden")
