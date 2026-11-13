"""NBA player prop source (points, steals, assists, rebounds, threes, PRA).

The stat tables store a FanDuel line, an 'o'/'u' flag and the American price of
that side (``fanduel_price``); rows without a price are skipped. They have no created_at, so ``generated_at`` is
None. Teams, event id and start time come from pred_nba_game_lines.
"""

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    AssistsProjections,
    NBAGameLines,
    PointsProjections,
    PRAProjections,
    ReboundsProjections,
    StealsProjections,
    ThreePointProjections,
)
from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources._basketball import prop_rows

_L = "fanduel_line"
_NBA_STAT_SPECS = [
    (PointsProjections, "points", "projected_points", _L, None),
    (StealsProjections, "steals", "projected_steals", _L, None),
    (AssistsProjections, "assists", "projected_assists", _L, None),
    (ReboundsProjections, "rebounds", "projected_rebounds", _L, None),
    (ThreePointProjections, "threes", "projected_three_pt_made", _L, None),
    (PRAProjections, "pra", "projected_pra", _L, None),
]
# BlocksProjections has no fanduel_line column.

_SIDES = {"O": "over", "OVER": "over", "U": "under", "UNDER": "under"}


def _side(row) -> str | None:
    return _SIDES.get((row.fanduel_over_under or "").strip().upper())


class PlayerPropSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        return prop_rows(
            self.db, _NBA_STAT_SPECS, NBAGameLines, "NBA", date_range, _side
        )
