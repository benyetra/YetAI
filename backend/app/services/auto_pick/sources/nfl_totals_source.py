"""
NFL totals source: NFLTotalsProjections joined to NFLGameLines on
(game_date, home, away). Built from the row's stored consensus quote (``best_*``);
without one, the side the projection sits on at the stored line and price (dropped
later as ``no_consensus_price``). ``created_at`` is refreshed by the ETL upsert.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import NFLGameLines, NFLTotalsProjections
from app.services.auto_pick.candidate import DateRange, projection_ref, to_naive_utc
from app.services.auto_pick.sources._basketball import fresh_keys, ou_quote
from app.services.auto_pick.sources._nfl_lines import line_event_id

log = logging.getLogger(__name__)


class NFLTotalsSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date
        try:
            with self.db.begin_nested():  # keep a failed query from aborting the run
                rows = (
                    self.db.query(NFLTotalsProjections)
                    .filter(NFLTotalsProjections.game_date == day)
                    .all()
                )
                lines = {
                    (g.home_team_name, g.away_team_name): g
                    for g in self.db.query(NFLGameLines)
                    .filter(NFLGameLines.game_date == day)
                    .all()
                }
        except Exception:
            log.exception("NFLTotalsSource: DB query failed")
            return []

        return totals_rows_from_nfl(rows, lines, day)


def totals_rows_from_nfl(rows, lines, day) -> list[dict]:
    """Pure: NFL totals rows + {(home, away): game line} -> candidate rows."""
    out: list[dict] = []
    for r in rows:
        gl = lines.get((r.home_team_name, r.away_team_name))
        if gl is None or r.projected_total is None:
            continue
        q = ou_quote(r, r.projected_total, r.market_total, gl.over_odds, gl.under_odds)
        if q is None:
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
                "projected_total": float(r.projected_total),
                "market_total": q["line"],
                "line_odds": q["odds"],
                "side": q["side"],
                "confidence_score": r.confidence_score,
                "edge": r.edge,
                "recommendation": r.recommendation,
                "injury_report": r.injury_report,
                "factors": r.factors,
                "generated_at": r.created_at,
                "commence_time": to_naive_utc(gl.game_time),
                "fair_prob": q["fair_prob"],
                **fresh_keys(q, r.created_at),
            }
        )
    return out
