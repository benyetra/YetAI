"""
MLB strikeout projection source for auto-pick.

Uses YetAI pick (projected K vs FanDuel line) with a minimum K-edge gate so
auto picks align with what users see on the MLB stats table.
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import Pitcher, StrikeoutProjections
from app.services.auto_pick.candidate import DateRange
from app.services.mlb_strikeout_pick import (
    pick_confidence_pct,
    projection_pick_side,
    qualifies_for_auto_pick,
)

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
            pitcher_meta = {p.pitcher_id: p for p in self.db.query(Pitcher).all()}
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
            if line_val is None or line_val <= 0:
                log.debug(
                    "MLBStrikeoutSource: skipping %s (%s) — no fanduel_line",
                    r.pitcher_name,
                    r.date,
                )
                continue

            side = (
                (r.fanduel_over_under or "").strip().lower()
                if r.fanduel_over_under
                else projection_pick_side(r.projected_strikeouts, line_val)
            )
            if side not in ("over", "under"):
                side = projection_pick_side(r.projected_strikeouts, line_val)
            if not qualifies_for_auto_pick(r.projected_strikeouts, line_val, side):
                log.debug(
                    "MLBStrikeoutSource: skipping %s — insufficient K edge",
                    r.pitcher_name,
                )
                continue

            meta = pitcher_meta.get(str(r.pitcher_id))
            prob_over = getattr(meta, "prob_over", None) if meta else None
            pick_edge_pct = getattr(meta, "pick_edge_pct", None) if meta else None
            confidence = getattr(r, "pick_confidence", None) or pick_confidence_pct(
                float(r.projected_strikeouts),
                float(line_val),
                prob_over=prob_over,
                ev_edge_pct=pick_edge_pct,
            )
            odds = -110
            if meta and getattr(meta, "fanduel_price", None):
                try:
                    price = int(meta.fanduel_price)
                    if price != 0:
                        odds = price
                except (TypeError, ValueError):
                    pass

            player_name = r.pitcher_name or f"pitcher_{r.pitcher_id}"
            event_id = f"mlb-prop-{r.date}-{r.pitcher_id}-strikeouts"

            out.append(
                {
                    "event_id": event_id,
                    "league": "MLB",
                    "player": player_name,
                    "stat": "strikeouts",
                    "line": float(line_val),
                    "odds": odds,
                    "projection": float(r.projected_strikeouts),
                    "side": side,
                    "sample_size": None,
                    "generated_at": r.date,
                    "model_confidence": confidence / 100.0,
                    "injury_flag": False,
                }
            )

        return out
