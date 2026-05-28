"""
Player prop source shim.

Aggregates NBA per-stat projection tables:
  - pred_points_projections   (PointsProjections)
  - pred_assists_projections  (AssistsProjections)
  - pred_rebounds_projections (ReboundsProjections)
  - pred_steals_projections   (StealsProjections)
  - pred_blocks_projections   (BlocksProjections)

COVERAGE NOTES:
  - MLB strikeout projections (pred_strikeout_projections) are NOT included here
    because their date range spans pitcher starts, not today's NBA slate. Add a
    separate MLBStrikeoutSource if needed.
  - Live moneyline odds are NOT joined here. The NBA stat tables store an optional
    `fanduel_line` / `fanduel_over_under` snapshot. We use fanduel_line as
    market_line and default to -110 odds. If fanduel_line is NULL the row is
    skipped (no market line → no bet candidate).
  - `event_id` cannot be derived from these tables (no game FK). We synthesize a
    deterministic key from (date, player_id, stat). The orchestrator dedupes by
    event_id so collisions are safe.
  - AssistsProjections and ReboundsProjections include optional FanDuel lines
    when the Odds API returns them.

Returns dicts shaped for PlayerPropCandidateProvider:
  Required: event_id, league, player, stat, line, odds, projection, side
  Optional: sample_size, generated_at, model_confidence, injury_flag
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    AssistsProjections,
    BlocksProjections,
    PointsProjections,
    ReboundsProjections,
    StealsProjections,
)
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)

# Mapping: (model_class, stat_label, projection_attr, line_attr, ou_attr)
# line_attr / ou_attr may be None when the table lacks those columns.
_NBA_STAT_SPECS = [
    (
        PointsProjections,
        "points",
        "projected_points",
        "fanduel_line",
        "fanduel_over_under",
    ),
    (
        StealsProjections,
        "steals",
        "projected_steals",
        "fanduel_line",
        "fanduel_over_under",
    ),
    (
        AssistsProjections,
        "assists",
        "projected_assists",
        "fanduel_line",
        "fanduel_over_under",
    ),
    (
        ReboundsProjections,
        "rebounds",
        "projected_rebounds",
        "fanduel_line",
        "fanduel_over_under",
    ),
    # BlocksProjections has no fanduel_line column.
]


class PlayerPropSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end
        out: list[dict] = []

        for model_cls, stat_label, proj_attr, line_attr, ou_attr in _NBA_STAT_SPECS:
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
                log.exception("PlayerPropSource: query failed for %s", stat_label)
                continue

            for r in rows:
                proj_val = getattr(r, proj_attr, None)
                if proj_val is None:
                    continue

                line_val = getattr(r, line_attr, None) if line_attr else None
                if line_val is None:
                    # No market line — cannot form a bet candidate
                    continue

                ou_raw = getattr(r, ou_attr, None) if ou_attr else None
                side = "over"
                if ou_raw and ou_raw.strip().upper() in ("UNDER", "U"):
                    side = "under"

                player_name = getattr(r, "player_name", None) or f"player_{r.player_id}"
                opponent = getattr(r, "opponent_team_name", None)
                event_id = f"nba-prop-{r.date}-{r.player_id}-{stat_label}"

                out.append(
                    {
                        "event_id": event_id,
                        "league": "NBA",
                        "player": player_name,
                        "stat": stat_label,
                        "line": float(line_val),
                        "odds": -110,  # No live odds column — use standard juice
                        "projection": float(proj_val),
                        "side": side,
                        "opponent": opponent,
                        "opponent_team_name": opponent,
                        "sample_size": None,
                        "generated_at": r.date,
                        "model_confidence": None,
                        "injury_flag": False,
                    }
                )

        return out
