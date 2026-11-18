"""
NHL totals (goals) projection source shim.

Queries pred_nhl_team_totals_predictions for game-level over/under markets.
The table stores draftkings_ou_line, over_odds, under_odds, and a
betting_recommendation — no separate game_lines join required.

The writer (etl/nhl/daily_predictions.py) stores ``betting_recommendation`` as
"OVER 6.0" / "UNDER 6.0" / "PASS" and place names ("Boston", "New York") for the
teams; full names are resolved from the team ids. Built from the row's stored consensus
quote (``best_*``); without one, the side the projection sits on at the stored line and
price (dropped later as ``no_consensus_price``). Rows are skipped without a line, a
price or a resolvable team.
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
from app.services.auto_pick.sources._basketball import fresh_keys, ou_quote
from app.services.auto_pick.sources._nhl_teams import nhl_full_name

log = logging.getLogger(__name__)


class NHLTotalsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date

        try:
            with self.db.begin_nested():  # keep a failed query from aborting the run
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

        return nhl_totals_rows_from(rows, day)


def nhl_totals_rows_from(rows, day) -> list[dict]:
    """Pure: NHL team-totals rows -> candidate rows (stored consensus quote)."""
    out: list[dict] = []
    for r in rows:
        if r.predicted_total_goals is None:
            continue
        q = ou_quote(
            r, r.predicted_total_goals, r.draftkings_ou_line, r.over_odds, r.under_odds
        )
        if q is None:
            continue
        home = nhl_full_name(r.home_team_id)
        away = nhl_full_name(r.away_team_id)
        if home is None or away is None:
            continue
        out.append(
            {
                "event_id": f"nhl-{r.game_date}-{home}-{away}",
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
                "market_total": q["line"],
                "side": q["side"],
                "line_odds": q["odds"],
                "commence_time": eastern_naive_to_utc(r.game_time_et),
                "confidence_score": (
                    r.confidence / 100.0 if r.confidence is not None else None
                ),
                "edge": r.edge,
                "recommendation": r.betting_recommendation,
                "injury_report": None,
                "factors": None,
                "generated_at": r.prediction_date,
                "fair_prob": q["fair_prob"],
                **fresh_keys(q, r.prediction_date),
            }
        )
    return out
