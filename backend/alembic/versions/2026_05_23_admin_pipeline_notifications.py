"""admin pipeline notifications

Adds two tables that record Celery pipeline lifecycle events (start /
finish / fail) for every orchestrator in PIPELINE_ORCHESTRATORS, and a
per-admin read receipt for those notifications.

Revision ID: 2026_05_23_anf
Revises: 186bd4461744
Create Date: 2026-05-23 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = "2026_05_23_anf"
down_revision: Union[str, Sequence[str], None] = "186bd4461744"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ADMIN_NOTIFICATION_EVENT = "adminnotificationevent"


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _enum_type_exists(conn, typname: str) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM pg_type WHERE typname = :n AND typtype = 'e'"),
            {"n": typname},
        ).fetchone()
        is not None
    )


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    if not _enum_type_exists(conn, ADMIN_NOTIFICATION_EVENT):
        conn.execute(
            text(
                f"CREATE TYPE {ADMIN_NOTIFICATION_EVENT} AS ENUM "
                "('started', 'finished', 'failed')"
            )
        )

    event_enum = sa.Enum(
        "started",
        "finished",
        "failed",
        name=ADMIN_NOTIFICATION_EVENT,
        create_type=False,
    )

    if not _has_table("admin_notifications"):
        op.create_table(
            "admin_notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_type", event_enum, nullable=False),
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

    if not _has_table("admin_notification_reads"):
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
    if _has_table("admin_notification_reads"):
        op.drop_table("admin_notification_reads")
    if _has_table("admin_notifications"):
        op.drop_index(
            "ix_admin_notifications_created_at", table_name="admin_notifications"
        )
        op.drop_index(
            "ix_admin_notifications_task_id", table_name="admin_notifications"
        )
        op.drop_index(
            "ix_admin_notifications_task_name", table_name="admin_notifications"
        )
        op.drop_index(
            "ix_admin_notifications_event_type", table_name="admin_notifications"
        )
        op.drop_table("admin_notifications")
    conn = op.get_bind()
    if _enum_type_exists(conn, ADMIN_NOTIFICATION_EVENT):
        conn.execute(text(f"DROP TYPE IF EXISTS {ADMIN_NOTIFICATION_EVENT}"))
