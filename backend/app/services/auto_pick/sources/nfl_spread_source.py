"""
NFL spread source: NFLSpreadProjections joined to NFLGameLines on
(game_date, home, away). ``projected_margin`` is home minus away.

Built from the row's stored consensus quote (``best_*``); without one, the side the
stored projection sits on at the stored line and price (dropped later as
``no_consensus_price``). ``created_at`` is refreshed by the ETL upsert, so it is the
row's generated_at and projected_at.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import NFLGameLines, NFLSpreadProjections
from app.services.auto_pick.candidate import DateRange, projection_ref, to_naive_utc
from app.services.auto_pick.sources._basketball import (
    anchor_md,
    fresh_keys,
    spread_quote,
)
from app.services.auto_pick.sources._nfl_lines import line_event_id

log = logging.getLogger(__name__)


class NFLSpreadSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date
        try:
            with self.db.begin_nested():  # keep a failed query from aborting the run
                rows = (
                    self.db.query(NFLSpreadProjections)
                    .filter(NFLSpreadProjections.game_date == day)
                    .all()
                )
                lines = {
                    (g.home_team_name, g.away_team_name): g
                    for g in self.db.query(NFLGameLines)
                    .filter(NFLGameLines.game_date == day)
                    .all()
                }
        except Exception:
            log.exception("NFLSpreadSource: DB query failed")
            return []

        return spread_rows_from_nfl(rows, lines, day)


def spread_rows_from_nfl(rows, lines, day) -> list[dict]:
    """Pure: NFL spread rows + {(home, away): game line} -> candidate rows.

    The stored consensus quote when there is one; the EV rule decides, not the
    projector's recommendation."""
    from app.services.etl._spread_model import NFL_CONFIG

    out: list[dict] = []
    for r in rows:
        gl = lines.get((r.home_team_name, r.away_team_name))
        if gl is None:
            continue
        q = spread_quote(r, gl.spread_home_odds, gl.spread_away_odds)
        if q is None or r.projected_margin is None:
            continue
        out.append(
            {
                "event_id": line_event_id(gl),
                "league": "NFL",
                "game_date": day,
                "home_team_name": r.home_team_name,
                "away_team_name": r.away_team_name,
                "projection_ref": projection_ref(
                    r,
                    game_date=r.game_date,
                    home_team_name=r.home_team_name,
                    away_team_name=r.away_team_name,
                ),
                "model_version": getattr(r, "model_version", None),
                "projected_margin": float(r.projected_margin),
                "market_spread_home": q["home_line"],
                "spread_odds": q["odds"],
                "side": q["side"],
                "confidence_score": r.confidence_score,
                "edge": r.edge,
                "recommendation": r.recommendation,
                "home_win_prob": r.home_win_prob,
                "factors": r.factors,
                "generated_at": r.created_at,
                "commence_time": to_naive_utc(gl.game_time),
                "fair_prob": q["fair_prob"],
                **fresh_keys(q, r.created_at),
                **anchor_md(r, NFL_CONFIG.win_prob_logistic_scale),
            }
        )
    return out
