"""WNBA totals source: HOME/AWAY|OVER/UNDER recommendation + stored game-line price."""

from sqlalchemy.orm import Session

from app.models.predictions_models import WNBAGameLines, WNBATotalsProjections
from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources._basketball import totals_rows


class WNBATotalsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        return totals_rows(
            self.db, WNBATotalsProjections, WNBAGameLines, "WNBA", date_range
        )
