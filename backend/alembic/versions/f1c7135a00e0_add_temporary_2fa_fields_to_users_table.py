"""Add temporary 2FA fields to users table

Revision ID: f1c7135a00e0
Revises: 1cfb8dd64dbd
Create Date: 2025-08-19 13:37:00.393084

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f1c7135a00e0'
down_revision: Union[str, Sequence[str], None] = '1cfb8dd64dbd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add temporary 2FA fields to users table
    op.add_column('users', sa.Column('temp_totp_secret', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('temp_backup_codes', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove temporary 2FA fields from users table
    op.drop_column('users', 'temp_backup_codes')
    op.drop_column('users', 'temp_totp_secret')
