"""NBA spread source: HOME/AWAY|OVER/UNDER recommendation + stored game-line price."""

from sqlalchemy.orm import Session

from app.models.predictions_models import NBAGameLines, NBASpreadProjections
from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources._basketball import spread_rows


class NBASpreadSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        return spread_rows(
            self.db, NBASpreadProjections, NBAGameLines, "NBA", date_range
        )
