"""Normalize player_analytics.game_script to double precision.

Revision ID: 20260607_pa_game_script
Revises: 20260606_wnba_fetch_log
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260607_pa_game_script"
down_revision: Union[str, None] = "20260606_wnba_fetch_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Some environments created game_script as varchar (e.g. seeded 'neutral').
    # Canonical schema is double precision (see create_player_analytics_table.sql).
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'player_analytics'
              AND column_name = 'game_script'
              AND udt_name IN ('varchar', 'text', 'bpchar')
          ) THEN
            ALTER TABLE player_analytics
            ALTER COLUMN game_script TYPE double precision
            USING CASE
              WHEN game_script IS NULL THEN NULL
              WHEN game_script ~ '^[+-]?([0-9]+(\\.[0-9]*)?|\\.[0-9]+)$'
                THEN game_script::double precision
              ELSE NULL
            END;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE player_analytics
        ALTER COLUMN game_script TYPE varchar(20)
        USING CASE
          WHEN game_script IS NULL THEN NULL
          ELSE game_script::text
        END;
        """
    )
