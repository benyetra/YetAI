"""
WNBA totals projection source for auto-pick.

Mirrors NBATotalsSource against pred_wnba_totals_projections + pred_wnba_game_lines.
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import WNBAGameLines, WNBATotalsProjections
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)


class WNBATotalsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end

        try:
            rows = (
                self.db.query(WNBATotalsProjections)
                .filter(
                    WNBATotalsProjections.game_date >= start,
                    WNBATotalsProjections.game_date <= end,
                )
                .all()
            )
        except Exception:
            log.exception("WNBATotalsSource: DB query failed")
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
                "WNBATotalsSource: game_lines join failed, continuing without odds"
            )
            game_lines = {}

        out: list[dict] = []
        for r in rows:
            if r.market_total is None:
                log.debug(
                    "WNBATotalsSource: skipping %s @ %s (%s) — no market_total",
                    r.away_team_name,
                    r.home_team_name,
                    r.game_date,
                )
                continue

            side = "over"
            if r.recommendation and "UNDER" in r.recommendation.upper():
                side = "under"

            gl = game_lines.get((r.game_date, r.home_team_name, r.away_team_name))
            event_id = (
                gl.odds_api_event_id
                if gl and gl.odds_api_event_id
                else f"wnba-{r.game_date}-{r.home_team_name}-{r.away_team_name}"
            )

            line_odds = -110
            if gl:
                if side == "over" and gl.over_odds is not None:
                    line_odds = gl.over_odds
                elif side == "under" and gl.under_odds is not None:
                    line_odds = gl.under_odds

            out.append(
                {
                    "event_id": event_id,
                    "league": "WNBA",
                    "game_date": r.game_date,
                    "home_team_name": r.home_team_name,
                    "away_team_name": r.away_team_name,
                    "projected_total": r.projected_total,
                    "market_total": r.market_total,
                    "side": side,
                    "line_odds": line_odds,
                    "confidence_score": r.confidence_score,
                    "edge": r.edge,
                    "recommendation": r.recommendation,
                    "injury_report": r.injury_report,
                    "factors": r.factors,
                    "generated_at": r.created_at,
                    "game_time": gl.game_time if gl else None,
                }
            )

        return out
