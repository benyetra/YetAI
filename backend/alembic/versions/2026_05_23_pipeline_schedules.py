"""pipeline schedule overrides

Adds the pipeline_schedules table — admin-editable Celery beat schedule
overrides. Empty by default; the DatabaseScheduler falls back to the
hardcoded beat_schedule entries when no row exists for a task.

Revision ID: 2026_05_23_psc
Revises: 2026_05_23_anf
Create Date: 2026-05-23 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "2026_05_23_psc"
down_revision: Union[str, Sequence[str], None] = "2026_05_23_anf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    """Upgrade schema."""
    if _has_table("pipeline_schedules"):
        return
    op.create_table(
        "pipeline_schedules",
        sa.Column("task_name", sa.String(length=255), primary_key=True),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("pipeline_schedules")
