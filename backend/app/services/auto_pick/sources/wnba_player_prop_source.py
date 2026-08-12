"""
WNBA player prop source for auto-pick.

Aggregates pred_wnba_{points,assists,rebounds}_projections (market_line column).
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    WNBAAssistsProjections,
    WNBAPointsProjections,
    WNBAPRAProjections,
    WNBAReboundsProjections,
    WNBAThreePtMadeProjections,
)
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)

_WNBA_STAT_SPECS = [
    (WNBAPointsProjections, "points", "projected_points"),
    (WNBAAssistsProjections, "assists", "projected_assists"),
    (WNBAReboundsProjections, "rebounds", "projected_rebounds"),
    (WNBAThreePtMadeProjections, "three_pt_made", "projected_three_pt_made"),
    (WNBAPRAProjections, "pra", "projected_pra"),
]


def _side_from_recommendation(recommendation: str | None) -> str:
    if recommendation and "UNDER" in recommendation.upper():
        return "under"
    return "over"


class WNBAPlayerPropSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end
        out: list[dict] = []

        for model_cls, stat_label, proj_attr in _WNBA_STAT_SPECS:
            try:
                rows = (
                    self.db.query(model_cls)
                    .filter(
                        model_cls.date >= start,
                        model_cls.date <= end,
                    )
                    .all()
                )
            except Exception:
                log.exception("WNBAPlayerPropSource: query failed for %s", stat_label)
                continue

            for r in rows:
                proj_val = getattr(r, proj_attr, None)
                line_val = getattr(r, "market_line", None)
                if proj_val is None or line_val is None:
                    continue

                player_name = getattr(r, "player_name", None) or f"player_{r.player_id}"
                opponent = getattr(r, "opponent_team_name", None)
                side = _side_from_recommendation(getattr(r, "recommendation", None))
                confidence = getattr(r, "confidence_score", None)
                model_conf = (
                    float(confidence) / 100.0 if confidence is not None else None
                )

                out.append(
                    {
                        "event_id": f"wnba-prop-{r.date}-{r.player_id}-{stat_label}",
                        "league": "WNBA",
                        "player": player_name,
                        "stat": stat_label,
                        "line": float(line_val),
                        "odds": -110,
                        "projection": float(proj_val),
                        "side": side,
                        "opponent": opponent,
                        "opponent_team_name": opponent,
                        "sample_size": None,
                        "generated_at": r.date,
                        "model_confidence": model_conf,
                        "injury_flag": False,
                    }
                )

        return out
