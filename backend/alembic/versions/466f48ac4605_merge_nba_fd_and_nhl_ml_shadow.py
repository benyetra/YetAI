"""merge_nba_fd_and_nhl_ml_shadow

Revision ID: 466f48ac4605
Revises: 20260525_nba_fd_core, 2026_05_25_nhl_ml_shadow
Create Date: 2026-05-25 11:31:13.480924

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "466f48ac4605"
down_revision: Union[str, Sequence[str], None] = (
    "20260525_nba_fd_core",
    "2026_05_25_nhl_ml_shadow",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
