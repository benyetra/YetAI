"""WNBA player prop source: market_line + OVER/UNDER recommendation, fanduel_price (rows without one are skipped)."""

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    WNBAAssistsProjections,
    WNBAGameLines,
    WNBAPointsProjections,
    WNBAPRAProjections,
    WNBAReboundsProjections,
    WNBAThreePtMadeProjections,
)
from app.services.auto_pick.candidate import DateRange
from app.services.auto_pick.sources._basketball import prop_rows

# created_at is refreshed by the ETL upsert on every run.
_WNBA_STAT_SPECS = [
    (WNBAPointsProjections, "points", "projected_points", "market_line", "created_at"),
    (
        WNBAAssistsProjections,
        "assists",
        "projected_assists",
        "market_line",
        "created_at",
    ),
    (
        WNBAReboundsProjections,
        "rebounds",
        "projected_rebounds",
        "market_line",
        "created_at",
    ),
    (
        WNBAThreePtMadeProjections,
        "threes",
        "projected_three_pt_made",
        "market_line",
        "created_at",
    ),
    (WNBAPRAProjections, "pra", "projected_pra", "market_line", "created_at"),
]


def _side(row) -> str | None:
    return {"OVER": "over", "UNDER": "under"}.get((row.recommendation or "").upper())


class WNBAPlayerPropSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        return prop_rows(
            self.db, _WNBA_STAT_SPECS, WNBAGameLines, "WNBA", date_range, _side
        )
