"""
NFL QB passing yards projection source shim.

Queries pred_qb_predictions for QB passing yards props.
Each row stores ou_line, over_odds, under_odds, and a betting_recommendation
directly — no separate game_lines join required.

Rows where ou_line is NULL are skipped (no market line → no candidate).

Returns dicts shaped for PlayerPropCandidateProvider:
  Required: event_id, league, player, stat, line, odds, projection, side
  Optional: sample_size, generated_at, model_confidence, injury_flag
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.predictions_models import QBPredictions
from app.services.auto_pick.candidate import DateRange

log = logging.getLogger(__name__)


class NFLQBPassingSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        # date_range.start/end are datetime instances. Normalize to day bounds
        # using timedelta to avoid month/year rollover bugs (e.g. day=31 + 1).
        start_dt = datetime(
            date_range.start.year, date_range.start.month, date_range.start.day
        )
        end_dt = datetime(
            date_range.end.year, date_range.end.month, date_range.end.day
        ) + timedelta(days=1)

        try:
            rows = (
                self.db.query(QBPredictions)
                .filter(
                    QBPredictions.game_date >= start_dt,
                    QBPredictions.game_date < end_dt,
                )
                .all()
            )
        except Exception:
            log.exception("NFLQBPassingSource: DB query failed")
            return []

        if not rows:
            return []

        out: list[dict] = []
        for r in rows:
            if r.predicted_passing_yards is None:
                continue

            if r.ou_line is None:
                log.debug(
                    "NFLQBPassingSource: skipping %s (%s) — no ou_line",
                    r.qb_player_name,
                    r.game_date,
                )
                continue

            rec = (r.betting_recommendation or "").upper()
            if "UNDER" in rec:
                side = "under"
                odds = r.under_odds if r.under_odds is not None else -110
            else:
                side = "over"
                odds = r.over_odds if r.over_odds is not None else -110

            game_date_val = (
                r.game_date.date() if isinstance(r.game_date, datetime) else r.game_date
            )
            event_id = f"nfl-prop-{game_date_val}-{r.qb_player_id}-passing_yards"

            out.append(
                {
                    "event_id": event_id,
                    "league": "NFL",
                    "player": r.qb_player_name,
                    "stat": "passing_yards",
                    "line": float(r.ou_line),
                    "odds": odds,
                    "projection": float(r.predicted_passing_yards),
                    "side": side,
                    "sample_size": None,
                    "generated_at": game_date_val,
                    "model_confidence": r.model_confidence,
                    "injury_flag": False,
                    "team": r.team_name,
                    "opponent": r.opponent_team_name,
                    "away_team_name": r.team_name,
                    "home_team_name": r.opponent_team_name,
                    "commence_time": r.game_date,
                }
            )

        return out
