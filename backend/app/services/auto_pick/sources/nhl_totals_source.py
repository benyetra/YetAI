"""
NHL totals (goals) projection source shim.

Queries pred_nhl_team_totals_predictions for game-level over/under markets.
The table stores draftkings_ou_line, over_odds, under_odds, and a
betting_recommendation — no separate game_lines join required.

The writer (etl/nhl/daily_predictions.py) stores ``betting_recommendation`` as
"OVER 6.0" / "UNDER 6.0" / "PASS" and place names ("Boston", "New York") for the
teams; full names are resolved from the team ids. Rows are skipped without a line,
an OVER/UNDER recommendation, a price for the side or a resolvable team.
``game_time_et`` is naive US Eastern; ``prediction_date`` is refreshed on every ETL
re-run (rows are deleted and re-inserted).

Returns dicts shaped for TotalsCandidateProvider:
  Required: event_id, home_team_name, away_team_name, projected_total,
            market_total, league, side
  Optional: line_odds, confidence_score, edge, recommendation,
            injury_report, factors, generated_at
"""

import logging
from sqlalchemy.orm import Session

from app.models.predictions_models import NHLTeamTotalsPredictions
from app.services.auto_pick.candidate import (
    DateRange,
    eastern_naive_to_utc,
    projection_ref,
)
from app.services.auto_pick.sources._nhl_teams import nhl_full_name

log = logging.getLogger(__name__)


class NHLTotalsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date

        try:
            rows = (
                self.db.query(NHLTeamTotalsPredictions)
                .filter(
                    NHLTeamTotalsPredictions.game_date == day,
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

            rec = (r.betting_recommendation or "").strip().upper().split(" ")[0]
            if rec == "OVER":
                side, line_odds = "over", r.over_odds
            elif rec == "UNDER":
                side, line_odds = "under", r.under_odds
            else:
                continue
            if line_odds is None:
                continue
            home = nhl_full_name(r.home_team_id)
            away = nhl_full_name(r.away_team_id)
            if home is None or away is None:
                continue

            event_id = f"nhl-{r.game_date}-{home}-{away}"

            out.append(
                {
                    "event_id": event_id,
                    "league": "NHL",
                    "game_date": day,
                    "home_team_name": home,
                    "away_team_name": away,
                    "projection_ref": projection_ref(
                        r,
                        game_date=r.game_date,
                        home_team_id=r.home_team_id,
                        away_team_id=r.away_team_id,
                    ),
                    "model_version": getattr(r, "model_version", None),
                    "projected_total": float(r.predicted_total_goals),
                    "market_total": float(r.draftkings_ou_line),
                    "side": side,
                    "line_odds": int(line_odds),
                    "commence_time": eastern_naive_to_utc(r.game_time_et),
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
