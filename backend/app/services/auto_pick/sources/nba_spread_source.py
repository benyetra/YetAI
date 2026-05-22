"""
NBA spread projection source shim.

Queries pred_nba_spread_projections, optionally joining pred_nba_game_lines
on (game_date, home_team_name, away_team_name) for actual spread odds.

Returns dicts shaped for SpreadCandidateProvider:
  Required: event_id, home_team_name, away_team_name, projected_margin,
            market_spread_home, league, side
  Optional: spread_odds, confidence_score, edge, recommendation,
            home_win_prob, factors, generated_at
"""
import logging
from datetime import date

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.database_models import AutoPickRunStatus  # noqa — import guard
from app.models.predictions_models import NBAGameLines, NBASpreadProjections
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)


class NBASpreadSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end

        try:
            rows = (
                self.db.query(NBASpreadProjections)
                .filter(
                    NBASpreadProjections.game_date >= start,
                    NBASpreadProjections.game_date <= end,
                )
                .all()
            )
        except Exception:
            log.exception("NBASpreadSource: DB query failed")
            return []

        if not rows:
            return []

        # Build a lookup from (game_date, home_team_name, away_team_name) -> NBAGameLines
        game_dates = {r.game_date for r in rows}
        try:
            game_lines_rows = (
                self.db.query(NBAGameLines)
                .filter(NBAGameLines.game_date.in_(game_dates))
                .all()
            )
            game_lines: dict[tuple, NBAGameLines] = {
                (gl.game_date, gl.home_team_name, gl.away_team_name): gl
                for gl in game_lines_rows
            }
        except Exception:
            log.warning("NBASpreadSource: game_lines join failed, continuing without odds")
            game_lines = {}

        out: list[dict] = []
        for r in rows:
            gl = game_lines.get((r.game_date, r.home_team_name, r.away_team_name))

            # Determine which side has positive edge; default to home
            side = "home"
            if r.edge is not None and r.recommendation:
                rec = (r.recommendation or "").upper()
                if "AWAY" in rec:
                    side = "away"

            # event_id: use odds_api_event_id if available, else a deterministic key
            event_id: str = (
                gl.odds_api_event_id
                if gl and gl.odds_api_event_id
                else f"nba-{r.game_date}-{r.home_team_name}-{r.away_team_name}"
            )

            spread_odds = None
            if gl:
                spread_odds = gl.spread_home_odds if side == "home" else gl.spread_away_odds

            out.append({
                "event_id": event_id,
                "league": "NBA",
                "game_date": r.game_date,
                "home_team_name": r.home_team_name,
                "away_team_name": r.away_team_name,
                "projected_margin": r.projected_margin,
                "market_spread_home": r.market_spread_home,
                "spread_odds": spread_odds if spread_odds is not None else -110,
                "side": side,
                "confidence_score": r.confidence_score,
                "edge": r.edge,
                "recommendation": r.recommendation,
                "home_win_prob": r.home_win_prob,
                "factors": r.factors,
                "generated_at": r.created_at,
            })

        return out
