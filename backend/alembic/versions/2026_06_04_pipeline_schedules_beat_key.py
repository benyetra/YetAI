"""Key pipeline_schedules by Celery beat entry key (not task_name).

Revision ID: 20260604_ps_beat_key
Revises: 20260527_yetai_result
Create Date: 2026-06-04

Allows separate overrides for beat entries that share one task (e.g.
mlb-projections-daily vs mlb-projections-safety-net).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260604_ps_beat_key"
down_revision: Union[str, None] = "20260527_yetai_result"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Primary beat slot when migrating legacy task_name-only rows.
_DEFAULT_BEAT_KEY_FOR_TASK: dict[str, str] = {
    "app.tasks.etl_pipeline.run_mlb_update_pipeline": "mlb-projections-daily",
    "app.tasks.etl_pipeline.run_mlb_store_actuals": "mlb-actuals-daily",
    "app.tasks.etl_pipeline.run_nba_update_pipeline": "nba-update-pipeline-daily",
    "app.tasks.etl_pipeline.run_wnba_update_pipeline": "wnba-update-pipeline-daily",
    "app.tasks.etl_pipeline.run_nfl_update_pipeline": "nfl-update-pipeline-daily",
    "app.tasks.etl_pipeline.run_nhl_update_pipeline": "nhl-update-pipeline-daily",
    "app.tasks.etl_pipeline.nba.spread_projector": "nba-spreads-accuracy-morning",
}


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not inspect(op.get_bind()).has_table("pipeline_schedules"):
        return
    if _has_column("pipeline_schedules", "beat_key"):
        return

    op.add_column(
        "pipeline_schedules",
        sa.Column("beat_key", sa.String(length=255), nullable=True),
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT task_name, hour, minute, enabled, updated_at, updated_by_user_id "
            "FROM pipeline_schedules"
        )
    ).fetchall()

    for row in rows:
        beat_key = _DEFAULT_BEAT_KEY_FOR_TASK.get(row.task_name, row.task_name)
        conn.execute(
            sa.text(
                "UPDATE pipeline_schedules SET beat_key = :beat_key WHERE task_name = :task_name"
            ),
            {"beat_key": beat_key, "task_name": row.task_name},
        )

    op.drop_constraint("pipeline_schedules_pkey", "pipeline_schedules", type_="primary")
    op.create_primary_key("pipeline_schedules_pkey", "pipeline_schedules", ["beat_key"])
    op.alter_column("pipeline_schedules", "beat_key", nullable=False)


def downgrade() -> None:
    if not inspect(op.get_bind()).has_table("pipeline_schedules"):
        return
    if not _has_column("pipeline_schedules", "beat_key"):
        return

    op.drop_constraint("pipeline_schedules_pkey", "pipeline_schedules", type_="primary")
    op.create_primary_key(
        "pipeline_schedules_pkey", "pipeline_schedules", ["task_name"]
    )
    op.drop_column("pipeline_schedules", "beat_key")
