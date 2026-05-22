"""
MLB strikeout projection source shim.

Queries pred_strikeout_projections for pitcher strikeout props.
The table stores a fanduel_line and fanduel_over_under per row, so we can
form bet candidates directly — no separate game_lines join required.

Rows without a fanduel_line are skipped (no market line → no candidate).

Returns dicts shaped for PlayerPropCandidateProvider:
  Required: event_id, league, player, stat, line, odds, projection, side
  Optional: sample_size, generated_at, model_confidence, injury_flag
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import StrikeoutProjections
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)


class MLBStrikeoutSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end

        try:
            rows = (
                self.db.query(StrikeoutProjections)
                .filter(
                    StrikeoutProjections.date >= start,
                    StrikeoutProjections.date <= end,
                )
                .all()
            )
        except Exception:
            log.exception("MLBStrikeoutSource: DB query failed")
            return []

        if not rows:
            return []

        out: list[dict] = []
        for r in rows:
            if r.projected_strikeouts is None:
                continue

            line_val = r.fanduel_line
            if line_val is None:
                log.debug(
                    "MLBStrikeoutSource: skipping %s (%s) — no fanduel_line",
                    r.pitcher_name,
                    r.date,
                )
                continue

            ou_raw = (r.fanduel_over_under or "").strip().upper()
            side = "under" if ou_raw in ("UNDER", "U") else "over"

            player_name = r.pitcher_name or f"pitcher_{r.pitcher_id}"
            event_id = f"mlb-prop-{r.date}-{r.pitcher_id}-strikeouts"

            out.append(
                {
                    "event_id": event_id,
                    "league": "MLB",
                    "player": player_name,
                    "stat": "strikeouts",
                    "line": float(line_val),
                    "odds": -110,
                    "projection": float(r.projected_strikeouts),
                    "side": side,
                    "sample_size": None,
                    "generated_at": r.date,
                    "model_confidence": None,
                    "injury_flag": False,
                }
            )

        return out
