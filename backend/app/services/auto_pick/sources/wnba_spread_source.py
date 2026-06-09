"""
WNBA spread projection source for auto-pick.

Mirrors NBASpreadSource against pred_wnba_spread_projections + pred_wnba_game_lines.
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import WNBAGameLines, WNBASpreadProjections
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)


class WNBASpreadSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end

        try:
            rows = (
                self.db.query(WNBASpreadProjections)
                .filter(
                    WNBASpreadProjections.game_date >= start,
                    WNBASpreadProjections.game_date <= end,
                )
                .all()
            )
        except Exception:
            log.exception("WNBASpreadSource: DB query failed")
            return []

        if not rows:
            return []

        game_dates = {r.game_date for r in rows}
        try:
            game_lines_rows = (
                self.db.query(WNBAGameLines)
                .filter(WNBAGameLines.game_date.in_(game_dates))
                .all()
            )
            game_lines: dict[tuple, WNBAGameLines] = {
                (gl.game_date, gl.home_team_name, gl.away_team_name): gl
                for gl in game_lines_rows
            }
        except Exception:
            log.warning(
                "WNBASpreadSource: game_lines join failed, continuing without odds"
            )
            game_lines = {}

        out: list[dict] = []
        for r in rows:
            gl = game_lines.get((r.game_date, r.home_team_name, r.away_team_name))

            side = "home"
            if r.recommendation and "AWAY" in (r.recommendation or "").upper():
                side = "away"

            event_id = (
                gl.odds_api_event_id
                if gl and gl.odds_api_event_id
                else f"wnba-{r.game_date}-{r.home_team_name}-{r.away_team_name}"
            )

            spread_odds = -110
            if gl:
                raw = gl.spread_home_odds if side == "home" else gl.spread_away_odds
                if raw is not None:
                    spread_odds = raw

            out.append(
                {
                    "event_id": event_id,
                    "league": "WNBA",
                    "game_date": r.game_date,
                    "home_team_name": r.home_team_name,
                    "away_team_name": r.away_team_name,
                    "projected_margin": r.projected_margin,
                    "market_spread_home": r.market_spread_home,
                    "spread_odds": spread_odds,
                    "side": side,
                    "confidence_score": r.confidence_score,
                    "edge": r.edge,
                    "recommendation": r.recommendation,
                    "home_win_prob": r.home_win_prob,
                    "factors": r.factors,
                    "generated_at": r.created_at,
                    "game_time": gl.game_time if gl else None,
                }
            )

        return out
