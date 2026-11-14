"""
NFL QB passing yards projection source.

Queries pred_qb_predictions (ou_line, over/under odds, betting_recommendation on
the row) and joins pred_nfl_game_lines for both team names, event id and kickoff.

``QBPredictions.game_date`` is a naive US Eastern kickoff (or midnight/noon
placeholder when the schedule is unknown), so the slate filter is the ET day.
``opponent_team_name`` is an abbreviation; the game is matched on ``team_name``.

Rows with no OVER/UNDER recommendation, no line, no price for the side, or no
matching game line are skipped.
"""

import logging
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models.predictions_models import QBPredictions
from app.services.auto_pick.candidate import DateRange, projection_ref, to_naive_utc
from app.services.auto_pick.sources._nfl_lines import (
    find_line,
    line_event_id,
    load_nfl_lines,
)

log = logging.getLogger(__name__)


class NFLQBPassingSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date
        start_et = datetime.combine(day, time.min)
        end_et = start_et + timedelta(days=1)

        try:
            rows = (
                self.db.query(QBPredictions)
                .filter(
                    QBPredictions.game_date >= start_et,
                    QBPredictions.game_date < end_et,
                )
                .all()
            )
            lines = load_nfl_lines(self.db, day) if rows else []
        except Exception:
            log.exception("NFLQBPassingSource: DB query failed")
            return []

        out: list[dict] = []
        for r in rows:
            if r.predicted_passing_yards is None or r.ou_line is None:
                continue

            rec = (r.betting_recommendation or "").strip().upper()
            if rec not in ("OVER", "UNDER"):
                continue
            side = rec.lower()
            odds = r.over_odds if side == "over" else r.under_odds
            if odds is None:
                continue

            gl = find_line(lines, r.team_name)
            if gl is None:
                log.debug("NFLQBPassingSource: no game line for %s", r.qb_player_name)
                continue

            out.append(
                {
                    "event_id": f"{line_event_id(gl)}-{r.qb_player_id}-passing_yards",
                    "league": "NFL",
                    "game_date": day,
                    "player": r.qb_player_name,
                    "stat": "passing_yards",
                    "projection_ref": projection_ref(
                        r, game_date=r.game_date, qb_player_id=r.qb_player_id
                    ),
                    "model_version": getattr(r, "model_version", None),
                    "line": float(r.ou_line),
                    "odds": int(odds),
                    "projection": float(r.predicted_passing_yards),
                    "side": side,
                    "sample_size": None,
                    # prediction_date is refreshed by the ETL on every re-run.
                    "generated_at": r.prediction_date,
                    "model_confidence": r.model_confidence,
                    "injury_flag": False,
                    "team": r.team_name,
                    "opponent": (
                        gl.away_team_name
                        if r.team_name == gl.home_team_name
                        else gl.home_team_name
                    ),
                    "home_team_name": gl.home_team_name,
                    "away_team_name": gl.away_team_name,
                    "commence_time": to_naive_utc(gl.game_time),
                }
            )

        return out
