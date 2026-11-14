"""
NFL receiving yards source (RecvYdsPredictions + NFLGameLines for teams/kickoff).

Rows with betting_recommendation other than OVER/UNDER, no ou_line, no price for
the side, or no matching game line are skipped. ``prediction_date`` is only set
when a row is created, so ``generated_at`` is None.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import RecvYdsPredictions
from app.services.auto_pick.candidate import DateRange, projection_ref, to_naive_utc
from app.services.auto_pick.sources._nfl_lines import (
    find_line,
    line_event_id,
    load_nfl_lines,
)

log = logging.getLogger(__name__)


class NFLReceivingYardsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date
        try:
            with self.db.begin_nested():  # keep a failed query from aborting the run
                rows = (
                    self.db.query(RecvYdsPredictions)
                    .filter(RecvYdsPredictions.game_date == day)
                    .all()
                )
                lines = load_nfl_lines(self.db, day) if rows else []
        except Exception:
            log.exception("NFLReceivingYardsSource: DB query failed")
            return []

        out: list[dict] = []
        for r in rows:
            if r.ou_line is None or r.predicted_receiving_yards is None:
                continue
            rec = (r.betting_recommendation or "").strip().upper()
            if rec not in ("OVER", "UNDER"):
                continue
            side = rec.lower()
            odds = r.over_odds if side == "over" else r.under_odds
            if odds is None:
                continue
            gl = find_line(lines, r.team_name, r.opponent_team_name)
            if gl is None:
                continue

            conf = r.confidence_score
            out.append(
                {
                    "event_id": f"{line_event_id(gl)}-{r.player_id}-receiving_yards",
                    "league": "NFL",
                    "game_date": day,
                    "player": r.player_name,
                    "stat": "receiving_yards",
                    "projection_ref": projection_ref(
                        r, game_date=r.game_date, player_id=r.player_id
                    ),
                    "model_version": getattr(r, "model_version", None),
                    "line": float(r.ou_line),
                    "odds": int(odds),
                    "projection": float(r.predicted_receiving_yards),
                    "side": side,
                    "sample_size": None,
                    "generated_at": None,
                    "model_confidence": conf,
                    "injury_flag": False,
                    "team": r.team_name,
                    "opponent": r.opponent_team_name,
                    "home_team_name": gl.home_team_name,
                    "away_team_name": gl.away_team_name,
                    "commence_time": to_naive_utc(gl.game_time),
                }
            )
        return out
