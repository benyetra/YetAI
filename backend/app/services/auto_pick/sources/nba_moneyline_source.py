"""
NBA moneyline source shim.

Joins pred_nba_spread_projections (home_win_prob) with pred_nba_game_lines
(moneyline_home / moneyline_away) on (game_date, home_team_name, away_team_name).

Rows where moneyline odds are missing in game_lines are skipped — without real
odds there is no moneyline market to evaluate.

Returns dicts shaped for MoneylineCandidateProvider:
  Required: event_id, home_team_name, away_team_name, home_win_prob,
            moneyline_home, moneyline_away, league, side
  Optional: confidence_score, generated_at
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import NBAGameLines, NBASpreadProjections
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)


class NBAMoneylineSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end

        try:
            spread_rows = (
                self.db.query(NBASpreadProjections)
                .filter(
                    NBASpreadProjections.game_date >= start,
                    NBASpreadProjections.game_date <= end,
                )
                .all()
            )
        except Exception:
            log.exception("NBAMoneylineSource: spread projections query failed")
            return []

        if not spread_rows:
            return []

        game_dates = {r.game_date for r in spread_rows}
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
            log.warning("NBAMoneylineSource: game_lines query failed — returning []")
            return []

        out: list[dict] = []
        for r in spread_rows:
            gl = game_lines.get((r.game_date, r.home_team_name, r.away_team_name))

            if gl is None or gl.moneyline_home is None or gl.moneyline_away is None:
                # No odds available — cannot construct a moneyline candidate
                log.debug(
                    "NBAMoneylineSource: skipping %s @ %s (%s) — no moneyline odds",
                    r.away_team_name,
                    r.home_team_name,
                    r.game_date,
                )
                continue

            # Provider picks side; we emit both in one row (provider picks from home_win_prob).
            # Determine recommended side from win_prob > 0.5.
            side = "home" if r.home_win_prob >= 0.5 else "away"

            event_id: str = (
                gl.odds_api_event_id
                if gl.odds_api_event_id
                else f"nba-{r.game_date}-{r.home_team_name}-{r.away_team_name}"
            )

            out.append(
                {
                    "event_id": event_id,
                    "league": "NBA",
                    "game_date": r.game_date,
                    "home_team_name": r.home_team_name,
                    "away_team_name": r.away_team_name,
                    "home_win_prob": r.home_win_prob,
                    "moneyline_home": gl.moneyline_home,
                    "moneyline_away": gl.moneyline_away,
                    "side": side,
                    "confidence_score": r.confidence_score,
                    "generated_at": r.created_at,
                }
            )

        return out
