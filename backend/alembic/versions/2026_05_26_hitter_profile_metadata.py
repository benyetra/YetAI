"""Add profile metadata columns to pred_hitter and pred_homer."""

from alembic import op
import sqlalchemy as sa

revision = "20260526_hitter_profile_meta"
down_revision = "20260526_mlb_profiles"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for table in ("pred_hitter", "pred_homer"):
        if not _has_column(table, "profile_version"):
            op.add_column(
                table, sa.Column("profile_version", sa.String(32), nullable=True)
            )
        if not _has_column(table, "matchup_contact_score"):
            op.add_column(
                table, sa.Column("matchup_contact_score", sa.Float(), nullable=True)
            )


def downgrade() -> None:
    for table in ("pred_homer", "pred_hitter"):
        if _has_column(table, "matchup_contact_score"):
            op.drop_column(table, "matchup_contact_score")
        if _has_column(table, "profile_version"):
            op.drop_column(table, "profile_version")
