"""
NFL receiving yards source (RecvYdsPredictions + NFLGameLines for teams/kickoff).

Built from the row's stored consensus quote (``best_*``); without one, the side the
projection sits on at the stored line and price (dropped later as
``no_consensus_price``). ``prediction_date`` is only set when a row is created, so
``generated_at`` is None and ``projected_at`` is the quote time. Rows with no line,
no price or no matching game line are skipped.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import RecvYdsPredictions
from app.services.auto_pick.candidate import DateRange, projection_ref, to_naive_utc
from app.services.auto_pick.sources._basketball import fresh_keys, ou_quote
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

        return recv_rows_from(rows, lines, day)


def recv_rows_from(rows, lines, day) -> list[dict]:
    """Pure: receiving rows + the day's NFL game lines -> candidate rows."""
    out: list[dict] = []
    for r in rows:
        if r.predicted_receiving_yards is None:
            continue
        q = ou_quote(
            r, r.predicted_receiving_yards, r.ou_line, r.over_odds, r.under_odds
        )
        if q is None:
            continue
        gl = find_line(lines, r.team_name, r.opponent_team_name)
        if gl is None:
            continue
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
                "line": q["line"],
                "odds": q["odds"],
                "projection": float(r.predicted_receiving_yards),
                "side": q["side"],
                "sample_size": None,
                "generated_at": None,
                "model_confidence": r.confidence_score,
                "injury_flag": False,
                "team": r.team_name,
                "opponent": r.opponent_team_name,
                "home_team_name": gl.home_team_name,
                "away_team_name": gl.away_team_name,
                "commence_time": to_naive_utc(gl.game_time),
                "fair_prob": q["fair_prob"],
            }
        )
        # No refresh stamp on these rows: freshness is the quote's. A row without a
        # quote has no consensus price either and is dropped on that.
        if "quoted_at" in q:
            out[-1].update(fresh_keys(q, q["quoted_at"]))
    return out
