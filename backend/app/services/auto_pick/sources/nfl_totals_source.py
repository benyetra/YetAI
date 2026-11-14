"""
NFL totals source: NFLTotalsProjections joined to NFLGameLines on
(game_date, home, away). Only OVER/UNDER recommendations with a stored price for
the side are emitted. ``created_at`` is refreshed by the ETL upsert.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import NFLGameLines, NFLTotalsProjections
from app.services.auto_pick.candidate import (
    DateRange,
    moved_line_edge,
    projection_ref,
    same_line,
    to_naive_utc,
)
from app.services.auto_pick.sources._nfl_lines import line_event_id

log = logging.getLogger(__name__)

# Mirrors TOTALS_EDGE_THRESHOLD in etl/nfl/totals_projector.py (that module is heavy to import).
_PLAY_THRESHOLD = 3.0


class NFLTotalsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date
        try:
            rows = (
                self.db.query(NFLTotalsProjections)
                .filter(NFLTotalsProjections.game_date == day)
                .all()
            )
            lines = {
                (g.home_team_name, g.away_team_name): g
                for g in self.db.query(NFLGameLines)
                .filter(NFLGameLines.game_date == day)
                .all()
            }
        except Exception:
            log.exception("NFLTotalsSource: DB query failed")
            return []

        out: list[dict] = []
        for r in rows:
            rec = (r.recommendation or "").strip().upper()
            if rec not in ("OVER", "UNDER") or r.market_total is None:
                continue
            gl = lines.get((r.home_team_name, r.away_team_name))
            if gl is None:
                continue
            side = rec.lower()
            edge = r.edge
            if not same_line(gl.total, r.market_total):
                # line moved since the projection: re-derive the edge on the current line
                edge = moved_line_edge(
                    "total", side, r.projected_total, gl.total, _PLAY_THRESHOLD
                )
                if edge is None:
                    continue
            odds = gl.over_odds if side == "over" else gl.under_odds
            if odds is None:
                continue
            out.append(
                {
                    "event_id": line_event_id(gl),
                    "league": "NFL",
                    "game_date": day,
                    "home_team_name": r.home_team_name,
                    "away_team_name": r.away_team_name,
                    "projection_ref": projection_ref(
                        r,
                        game_date=r.game_date,
                        home_team_name=r.home_team_name,
                        away_team_name=r.away_team_name,
                    ),
                    "model_version": getattr(r, "model_version", None),
                    "projected_total": float(r.projected_total),
                    "market_total": float(gl.total),
                    "line_odds": int(odds),
                    "side": side,
                    "confidence_score": r.confidence_score,
                    "edge": edge,
                    "recommendation": r.recommendation,
                    "injury_report": r.injury_report,
                    "factors": r.factors,
                    "generated_at": r.created_at,
                    "commence_time": to_naive_utc(gl.game_time),
                }
            )
        return out
