"""
NBA totals projection source shim.

Queries pred_nba_totals_projections, optionally joining pred_nba_game_lines
on (game_date, home_team_name, away_team_name) for over/under odds.

Returns dicts shaped for TotalsCandidateProvider:
  Required: event_id, home_team_name, away_team_name, projected_total,
            market_total, league, side
  Optional: line_odds, confidence_score, edge, recommendation,
            injury_report, factors, generated_at
"""
import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import NBAGameLines, NBATotalsProjections
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)


class NBATotalsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end

        try:
            rows = (
                self.db.query(NBATotalsProjections)
                .filter(
                    NBATotalsProjections.game_date >= start,
                    NBATotalsProjections.game_date <= end,
                )
                .all()
            )
        except Exception:
            log.exception("NBATotalsSource: DB query failed")
            return []

        if not rows:
            return []

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
            log.warning("NBATotalsSource: game_lines join failed, continuing without odds")
            game_lines = {}

        out: list[dict] = []
        for r in rows:
            gl = game_lines.get((r.game_date, r.home_team_name, r.away_team_name))

            # Skip rows missing market_total — provider needs it for the selection label
            if r.market_total is None:
                log.debug(
                    "NBATotalsSource: skipping %s @ %s (%s) — no market_total",
                    r.away_team_name,
                    r.home_team_name,
                    r.game_date,
                )
                continue

            # Determine side from recommendation
            side = "over"
            if r.recommendation:
                rec = r.recommendation.upper()
                if "UNDER" in rec:
                    side = "under"

            event_id: str = (
                gl.odds_api_event_id
                if gl and gl.odds_api_event_id
                else f"nba-{r.game_date}-{r.home_team_name}-{r.away_team_name}"
            )

            line_odds = -110
            if gl:
                if side == "over" and gl.over_odds is not None:
                    line_odds = gl.over_odds
                elif side == "under" and gl.under_odds is not None:
                    line_odds = gl.under_odds

            out.append({
                "event_id": event_id,
                "league": "NBA",
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
            })

        return out
