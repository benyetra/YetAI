"""
NFL spread source: NFLSpreadProjections joined to NFLGameLines on
(game_date, home, away). ``projected_margin`` is home minus away.

Only HOME/AWAY recommendations with a stored price for the picked side are
emitted (NO_PLAY / missing price -> skipped). ``created_at`` is refreshed by
the ETL upsert, so it is the row's generated_at.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import NFLGameLines, NFLSpreadProjections
from app.services.auto_pick.candidate import (
    DateRange,
    moved_line_edge,
    projection_ref,
    same_line,
    to_naive_utc,
)
from app.services.auto_pick.sources._nfl_lines import line_event_id

log = logging.getLogger(__name__)


class NFLSpreadSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date
        try:
            rows = (
                self.db.query(NFLSpreadProjections)
                .filter(NFLSpreadProjections.game_date == day)
                .all()
            )
            lines = {
                (g.home_team_name, g.away_team_name): g
                for g in self.db.query(NFLGameLines)
                .filter(NFLGameLines.game_date == day)
                .all()
            }
        except Exception:
            log.exception("NFLSpreadSource: DB query failed")
            return []

        out: list[dict] = []
        for r in rows:
            rec = (r.recommendation or "").strip().upper()
            if rec not in ("HOME", "AWAY") or r.market_spread_home is None:
                continue
            gl = lines.get((r.home_team_name, r.away_team_name))
            if gl is None:
                continue
            side = rec.lower()
            edge = r.edge
            if not same_line(gl.spread_home, r.market_spread_home):
                # line moved since the projection: re-derive the edge on the current line
                from app.services.etl._spread_model import NFL_CONFIG

                edge = moved_line_edge(
                    "spread",
                    side,
                    r.projected_margin,
                    gl.spread_home,
                    NFL_CONFIG.edge_threshold,
                )
                if edge is None:
                    continue
            odds = gl.spread_home_odds if side == "home" else gl.spread_away_odds
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
                    "projected_margin": float(r.projected_margin),
                    "market_spread_home": float(gl.spread_home),
                    "spread_odds": int(odds),
                    "side": side,
                    "confidence_score": r.confidence_score,
                    "edge": edge,
                    "recommendation": r.recommendation,
                    "home_win_prob": r.home_win_prob,
                    "factors": r.factors,
                    "generated_at": r.created_at,
                    "commence_time": to_naive_utc(gl.game_time),
                }
            )
        return out
