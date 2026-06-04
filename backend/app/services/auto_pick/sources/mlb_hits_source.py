"""
MLB 1+ hit projection source for auto-pick (pred_hitter board).

Used for straight hit props and as legs in 2-leg hit parlays.
"""

import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.predictions_models import Hitter
from app.services.auto_pick.candidate import DateRange
from app.services.mlb_hit_pick import (
    DEFAULT_HIT_LINE,
    DEFAULT_HIT_ODDS,
    hit_confidence_pct,
    projection_from_combined_score,
    qualifies_for_hit_auto_pick,
)

log = logging.getLogger(__name__)


class MLBHitsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start = date_range.start
        end = date_range.end

        try:
            rows = (
                self.db.query(Hitter)
                .filter(
                    Hitter.game_time >= start,
                    Hitter.game_time <= end,
                )
                .all()
            )
        except Exception:
            log.exception("MLBHitsSource: DB query failed")
            return []

        out: list[dict] = []
        for r in rows:
            if not qualifies_for_hit_auto_pick(r.combined_score):
                continue

            player_name = r.player_name or f"player_{r.player_id}"
            projection = projection_from_combined_score(float(r.combined_score))
            confidence = hit_confidence_pct(float(r.combined_score))
            event_id = f"mlb-hit-{r.game_id}-{r.player_id}"

            out.append(
                {
                    "event_id": event_id,
                    "league": "MLB",
                    "player": player_name,
                    "stat": "hits",
                    "line": float(DEFAULT_HIT_LINE),
                    "odds": DEFAULT_HIT_ODDS,
                    "projection": projection,
                    "side": "over",
                    "sample_size": r.hits_last_10_games,
                    "generated_at": r.game_time.date() if r.game_time else None,
                    "model_confidence": confidence / 100.0,
                    "injury_flag": False,
                    "team": r.team,
                    "opponent": r.opponent,
                    "away_team_name": r.team,
                    "home_team_name": r.opponent,
                    "commence_time": r.game_time,
                    "combined_score": float(r.combined_score),
                    "game_id": str(r.game_id),
                }
            )

        return out
