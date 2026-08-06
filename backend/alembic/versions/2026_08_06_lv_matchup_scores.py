"""Normalize lv_matchups score column names to team_a_score / team_b_score.

Prod (local P1) used PRD names ``team_a_score``/``team_b_score``. The merged
create migration used ``score_a``/``score_b`` for fresh DBs. Align everything
to the PRD names.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260806_lv_matchup_scores"
down_revision = "20260806_lv_vault_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("lv_matchups")}
    if "score_a" in cols and "team_a_score" not in cols:
        op.alter_column(
            "lv_matchups",
            "score_a",
            new_column_name="team_a_score",
            existing_type=sa.Float(),
            existing_nullable=True,
        )
    if "score_b" in cols and "team_b_score" not in cols:
        op.alter_column(
            "lv_matchups",
            "score_b",
            new_column_name="team_b_score",
            existing_type=sa.Float(),
            existing_nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("lv_matchups")}
    if "team_a_score" in cols and "score_a" not in cols:
        op.alter_column(
            "lv_matchups",
            "team_a_score",
            new_column_name="score_a",
            existing_type=sa.Float(),
            existing_nullable=True,
        )
    if "team_b_score" in cols and "score_b" not in cols:
        op.alter_column(
            "lv_matchups",
            "team_b_score",
            new_column_name="score_b",
            existing_type=sa.Float(),
            existing_nullable=True,
        )
