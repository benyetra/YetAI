"""admin pipeline notifications

Adds two tables that record Celery pipeline lifecycle events (start /
finish / fail) for every orchestrator in PIPELINE_ORCHESTRATORS, and a
per-admin read receipt for those notifications.

Revision ID: 2026_05_23_anf
Revises: 186bd4461744
Create Date: 2026-05-23 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2026_05_23_anf"
down_revision: Union[str, Sequence[str], None] = "186bd4461744"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "admin_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_type",
            sa.Enum(
                "started",
                "finished",
                "failed",
                name="adminnotificationevent",
            ),
            nullable=False,
        ),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("pipeline_label", sa.String(length=255), nullable=False),
        sa.Column("sport", sa.String(length=20)),
        sa.Column("task_id", sa.String(length=64)),
        sa.Column("status", sa.String(length=32)),
        sa.Column("duration_s", sa.Float()),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("error_traceback", sa.Text()),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_admin_notifications_event_type",
        "admin_notifications",
        ["event_type"],
    )
    op.create_index(
        "ix_admin_notifications_task_name",
        "admin_notifications",
        ["task_name"],
    )
    op.create_index(
        "ix_admin_notifications_task_id",
        "admin_notifications",
        ["task_id"],
    )
    op.create_index(
        "ix_admin_notifications_created_at",
        "admin_notifications",
        ["created_at"],
    )

    op.create_table(
        "admin_notification_reads",
        sa.Column(
            "notification_id",
            sa.Integer(),
            sa.ForeignKey("admin_notifications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "read_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("admin_notification_reads")
    op.drop_index("ix_admin_notifications_created_at", table_name="admin_notifications")
    op.drop_index("ix_admin_notifications_task_id", table_name="admin_notifications")
    op.drop_index("ix_admin_notifications_task_name", table_name="admin_notifications")
    op.drop_index("ix_admin_notifications_event_type", table_name="admin_notifications")
    op.drop_table("admin_notifications")
    sa.Enum(name="adminnotificationevent").drop(op.get_bind(), checkfirst=True)
