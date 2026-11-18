"""NBA moneyline source.

Built from the spread row's stored consensus moneyline quote (``ml_best_*``): the side,
price and no-vig probability the other books agree on. The unchanged EV gates decide.
A row with no consensus price still yields a candidate (the stored-projection side at the
stored moneyline, no fair_prob) so it is dropped as ``no_consensus_price``.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import NBAGameLines, NBASpreadProjections
from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources._basketball import _base, consensus_moneyline_row
from app.services.etl._spread_model import NBA_CONFIG

log = logging.getLogger(__name__)


def moneyline_rows_from(rows, gls) -> list[dict]:
    """Pure: NBA spread rows + {(home, away): game line} -> moneyline candidate rows."""
    out = []
    for r in rows:
        gl = gls.get((r.home_team_name, r.away_team_name))
        row = gl and consensus_moneyline_row(
            r,
            gl,
            _base(gl, "NBA", r.game_date, r.home_team_name, r.away_team_name),
            NBA_CONFIG.win_prob_logistic_scale,
        )
        if row:
            out.append(row)
    return out


class NBAMoneylineSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        try:
            with self.db.begin_nested():  # keep a failed query from aborting the run
                rows = (
                    self.db.query(NBASpreadProjections)
                    .filter(NBASpreadProjections.game_date == date_range.slate_date)
                    .all()
                )
                gls = {
                    (g.home_team_name, g.away_team_name): g
                    for g in self.db.query(NBAGameLines)
                    .filter(NBAGameLines.game_date == date_range.slate_date)
                    .all()
                }
        except Exception:
            log.exception("NBAMoneylineSource: query failed")
            return []
        return moneyline_rows_from(rows, gls)
