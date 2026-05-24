"""
NHL goalie saves projection source shim.

Queries pred_nhl_goalie_predictions for saves props.
Each row already stores saves_line, over_odds, under_odds and a
betting_recommendation — no separate game_lines join required.

Rows where saves_line is NULL or line_available is False are skipped.

Returns dicts shaped for PlayerPropCandidateProvider:
  Required: event_id, league, player, stat, line, odds, projection, side
  Optional: sample_size, generated_at, model_confidence, injury_flag
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.predictions_models import NHLGoaliePredictions
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)


class NHLGoalieSavesSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        start: date = date_range.start
        end: date = date_range.end

        try:
            rows = (
                self.db.query(NHLGoaliePredictions)
                .filter(
                    NHLGoaliePredictions.game_date >= start,
                    NHLGoaliePredictions.game_date <= end,
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
                log.debug(
                    "NHLGoalieSavesSource: skipping %s (%s) — no saves_line",
                    r.goalie_name,
                    r.game_date,
                )
                continue

            # Determine side from betting_recommendation or raw comparison
            rec = (r.betting_recommendation or "").upper()
            if "UNDER" in rec:
                side = "under"
                odds = r.under_odds if r.under_odds is not None else -110
            else:
                side = "over"
                odds = r.over_odds if r.over_odds is not None else -110

            event_id = f"nhl-prop-{r.game_date}-{r.goalie_id}-saves"
            if r.is_home is True:
                away_team_name = r.opponent_team_name
                home_team_name = r.team_name
            elif r.is_home is False:
                away_team_name = r.team_name
                home_team_name = r.opponent_team_name
            else:
                away_team_name = r.team_name
                home_team_name = r.opponent_team_name

            out.append(
                {
                    "event_id": event_id,
                    "league": "NHL",
                    "player": r.goalie_name,
                    "stat": "saves",
                    "line": float(r.saves_line),
                    "odds": odds,
                    "projection": float(r.predicted_saves),
                    "side": side,
                    "sample_size": None,
                    "generated_at": r.game_date,
                    "model_confidence": (
                        r.confidence / 100.0 if r.confidence is not None else None
                    ),
                    "injury_flag": (
                        bool(r.was_scratch) if r.was_scratch is not None else False
                    ),
                    "team": r.team_name,
                    "opponent": r.opponent_team_name,
                    "away_team_name": away_team_name,
                    "home_team_name": home_team_name,
                    "commence_time": r.game_time,
                }
            )

        return out
