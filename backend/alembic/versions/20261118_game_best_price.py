"""Best price and no-vig consensus on game-line and NFL/NHL prop rows.

best_book / best_line / best_price / best_side / best_fair_prob / best_ev / best_quoted_at
(the shape the NBA prop tables use, plus the side the quote is for) on the NBA and NFL
spread and totals rows, the NFL passing / receiving yards rows and the NHL goalie saves and
team totals rows. The two spread tables also carry the moneyline's quote (ml_best_*; a
moneyline has no line). All nullable.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_game_best_price"
down_revision: Union[str, None] = "20261118_nhl_goalie_uq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    "pred_nba_spread_projections",
    "pred_nba_totals_projections",
    "pred_nfl_spread_projections",
    "pred_nfl_totals_projections",
    "pred_qb_predictions",
    "pred_recv_yds_predictions",
    "pred_nhl_goalie_predictions",
    "pred_nhl_team_totals_predictions",
]
ML_TABLES = ["pred_nba_spread_projections", "pred_nfl_spread_projections"]

BEST = [
    ("best_book", "VARCHAR(64)", sa.String(64)),
    ("best_line", "DOUBLE PRECISION", sa.Float),
    ("best_price", "INTEGER", sa.Integer),
    ("best_side", "VARCHAR(8)", sa.String(8)),
    ("best_fair_prob", "DOUBLE PRECISION", sa.Float),
    ("best_ev", "DOUBLE PRECISION", sa.Float),
    ("best_quoted_at", "TIMESTAMP WITHOUT TIME ZONE", sa.DateTime),
]
ML_BEST = [("ml_" + n, pg, t) for n, pg, t in BEST if n != "best_line"]


def _columns():
    for table in TABLES:
        yield table, BEST
    for table in ML_TABLES:
        yield table, ML_BEST


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        for table, cols in _columns():
            for name, pg_type, _ in cols:
                op.execute(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {pg_type}"
                )
        return

    inspector = sa.inspect(bind)
    for table, cols in _columns():
        have = {c["name"] for c in inspector.get_columns(table)}
        for name, _, sa_type in cols:
            if name not in have:
                op.add_column(table, sa.Column(name, sa_type))
                have.add(name)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        for table, cols in _columns():
            for name, _, _ in cols:
                op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {name}")
        return
    inspector = sa.inspect(bind)
    for table, cols in _columns():
        have = {c["name"] for c in inspector.get_columns(table)}
        for name, _, _ in cols:
            if name in have:
                with op.batch_alter_table(table) as batch:
                    batch.drop_column(name)
