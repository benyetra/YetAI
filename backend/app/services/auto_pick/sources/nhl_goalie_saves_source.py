"""
NHL goalie saves projection source shim.

Queries pred_nhl_goalie_predictions for saves props.
Each row already stores saves_line, over_odds, under_odds and a
betting_recommendation — no separate game_lines join required.

The writer (etl/nhl/daily_predictions.py) sets ``saves_line`` / odds when a book
line exists but never sets ``line_available``; it writes only starter-confirmed
slots (``starter_confirmed`` True). Rows are skipped unless ``saves_line`` is set,
the starter is confirmed and the recommendation is "OVER x" / "UNDER x" with a price
for that side. Team columns are place names; full names come from the team ids.
``game_time`` is naive US Eastern; ``prediction_date`` is refreshed on every run.

Returns dicts shaped for PlayerPropCandidateProvider:
  Required: event_id, league, player, stat, line, odds, projection, side
  Optional: sample_size, generated_at, model_confidence, injury_flag
"""

import logging
from sqlalchemy.orm import Session

from app.models.predictions_models import NHLGoaliePredictions
from app.services.auto_pick.candidate import DateRange, eastern_naive_to_utc
from app.services.auto_pick.sources._nhl_teams import nhl_full_name

log = logging.getLogger(__name__)


class NHLGoalieSavesSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date

        try:
            rows = (
                self.db.query(NHLGoaliePredictions)
                .filter(
                    NHLGoaliePredictions.game_date == day,
                )
                .all()
            )
        except Exception:
            log.exception("NHLGoalieSavesSource: DB query failed")
            return []

        if not rows:
            return []

        out: list[dict] = []
        for r in rows:
            if r.predicted_saves is None:
                continue

            if r.saves_line is None:
                continue
            if not r.starter_confirmed:
                continue

            rec = (r.betting_recommendation or "").strip().upper()
            if rec.startswith("OVER"):
                side, odds = "over", r.over_odds
            elif rec.startswith("UNDER"):
                side, odds = "under", r.under_odds
            else:
                continue
            if odds is None or r.is_home is None:
                continue

            team, opponent = nhl_full_name(r.team_id), nhl_full_name(r.opponent_team_id)
            if team is None or opponent is None:
                continue

            event_id = f"nhl-prop-{r.game_date}-{r.goalie_id}-saves"
            if r.is_home:
                away_team_name, home_team_name = opponent, team
            else:
                away_team_name, home_team_name = team, opponent

            out.append(
                {
                    "event_id": event_id,
                    "league": "NHL",
                    "game_date": day,
                    "player": r.goalie_name,
                    "stat": "saves",
                    "line": float(r.saves_line),
                    "odds": int(odds),
                    "projection": float(r.predicted_saves),
                    "side": side,
                    "sample_size": None,
                    "generated_at": r.prediction_date,
                    "model_confidence": (
                        r.confidence / 100.0 if r.confidence is not None else None
                    ),
                    "injury_flag": (
                        bool(r.was_scratch) if r.was_scratch is not None else False
                    ),
                    "team": team,
                    "opponent": opponent,
                    "away_team_name": away_team_name,
                    "home_team_name": home_team_name,
                    "commence_time": eastern_naive_to_utc(r.game_time),
                }
            )

        return out
