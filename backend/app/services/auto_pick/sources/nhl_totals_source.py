"""
NHL totals (goals) projection source shim.

Queries pred_nhl_team_totals_predictions for game-level over/under markets.
The table stores draftkings_ou_line, over_odds, under_odds, and a
betting_recommendation — no separate game_lines join required.

Rows where draftkings_ou_line is NULL are skipped (no market line → no candidate).

Returns dicts shaped for TotalsCandidateProvider:
  Required: event_id, home_team_name, away_team_name, projected_total,
            market_total, league, side
  Optional: line_odds, confidence_score, edge, recommendation,
            injury_report, factors, generated_at
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import NHLTeamTotalsPredictions
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)


class NHLTotalsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end

        try:
            rows = (
                self.db.query(NHLTeamTotalsPredictions)
                .filter(
                    NHLTeamTotalsPredictions.game_date >= start,
                    NHLTeamTotalsPredictions.game_date <= end,
                )
                .all()
            )
        except Exception:
            log.exception("NHLTotalsSource: DB query failed")
            return []

        if not rows:
            return []

        out: list[dict] = []
        for r in rows:
            if r.draftkings_ou_line is None:
                log.debug(
                    "NHLTotalsSource: skipping %s @ %s (%s) — no draftkings_ou_line",
                    r.away_team_name,
                    r.home_team_name,
                    r.game_date,
                )
                continue

            rec = (r.betting_recommendation or "").upper()
            if "UNDER" in rec:
                side = "under"
                line_odds = r.under_odds if r.under_odds is not None else -110
            else:
                side = "over"
                line_odds = r.over_odds if r.over_odds is not None else -110

            event_id = f"nhl-{r.game_date}-{r.home_team_name}-{r.away_team_name}"

            out.append(
                {
                    "event_id": event_id,
                    "league": "NHL",
                    "game_date": r.game_date,
                    "home_team_name": r.home_team_name,
                    "away_team_name": r.away_team_name,
                    "projected_total": float(r.predicted_total_goals),
                    "market_total": float(r.draftkings_ou_line),
                    "side": side,
                    "line_odds": line_odds,
                    "confidence_score": (
                        r.confidence / 100.0 if r.confidence is not None else None
                    ),
                    "edge": r.edge,
                    "recommendation": r.betting_recommendation,
                    "injury_report": None,
                    "factors": None,
                    "generated_at": r.prediction_date,
                }
            )

        return out
