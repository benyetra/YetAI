"""NFL moneyline source: NFLSpreadProjections joined to NFLGameLines.

Same shape as the NBA moneyline source: the row's stored consensus moneyline quote
(``ml_best_*``), or the stored-projection side at the stored price (dropped later as
``no_consensus_price``).
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import NFLGameLines, NFLSpreadProjections
from app.services.auto_pick.candidate import DateRange, to_naive_utc
from app.services.auto_pick.sources._basketball import consensus_moneyline_row
from app.services.auto_pick.sources._nfl_lines import line_event_id
from app.services.etl._spread_model import NFL_CONFIG

log = logging.getLogger(__name__)


def moneyline_rows_from_nfl(rows, lines, day) -> list[dict]:
    """Pure: NFL spread rows + {(home, away): game line} -> moneyline candidate rows."""
    out = []
    for r in rows:
        gl = lines.get((r.home_team_name, r.away_team_name))
        row = gl and consensus_moneyline_row(
            r,
            gl,
            {
                "event_id": line_event_id(gl),
                "league": "NFL",
                "game_date": day,
                "home_team_name": r.home_team_name,
                "away_team_name": r.away_team_name,
                "commence_time": to_naive_utc(gl.game_time),
            },
            NFL_CONFIG.win_prob_logistic_scale,
        )
        if row:
            out.append(row)
    return out


class NFLMoneylineSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date
        try:
            with self.db.begin_nested():  # keep a failed query from aborting the run
                rows = (
                    self.db.query(NFLSpreadProjections)
                    .filter(NFLSpreadProjections.game_date == day)
                    .all()
                )
                lines = {
                    (g.home_team_name, g.away_team_name): g
                    for g in self.db.query(NFLGameLines)
                    .filter(NFLGameLines.game_date == day)
                    .all()
                }
        except Exception:
            log.exception("NFLMoneylineSource: DB query failed")
            return []
        return moneyline_rows_from_nfl(rows, lines, day)
