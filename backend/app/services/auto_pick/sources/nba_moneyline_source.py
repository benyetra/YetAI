"""NBA moneyline source.

No ML recommendation is stored. Pick the side whose model win probability beats
the no-vig implied probability of the two stored moneylines, and only when the
model's own part (win prob minus the spread's market win prob) agrees and is
at least ML_MIN_MODEL_EDGE.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import NBAGameLines, NBASpreadProjections
from app.services.auto_pick.candidate import DateRange, projection_ref, to_naive_utc

log = logging.getLogger(__name__)


# Model part of the win probability (model minus the market's own); below this the
# row only restates the spread-to-moneyline mapping (replay 2026-11-14: ROI -0.17).
ML_MIN_MODEL_EDGE = 0.02


def _implied(american: int) -> float:
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


class NBAMoneylineSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        try:
            with self.db.begin_nested():  # keep a failed query from aborting the run
                rows = (
                    self.db.query(NBASpreadProjections)
                    .filter(NBASpreadProjections.game_date == date_range.slate_date)
                    .all()
                )
                gls = {
                    (g.home_team_name, g.away_team_name): g
                    for g in self.db.query(NBAGameLines)
                    .filter(NBAGameLines.game_date == date_range.slate_date)
                    .all()
                }
        except Exception:
            log.exception("NBAMoneylineSource: query failed")
            return []
        out = []
        for r in rows:
            gl = gls.get((r.home_team_name, r.away_team_name))
            if gl is None or gl.moneyline_home is None or gl.moneyline_away is None:
                continue
            ih, ia = _implied(gl.moneyline_home), _implied(gl.moneyline_away)
            edge = r.home_win_prob - ih / (ih + ia)
            f = r.factors if isinstance(r.factors, dict) else {}
            market_p = f.get("market_win_prob")
            if market_p is None:
                continue
            model_part = r.home_win_prob - market_p
            if abs(model_part) < ML_MIN_MODEL_EDGE or (model_part > 0) != (edge > 0):
                continue
            out.append(
                {
                    "event_id": gl.odds_api_event_id
                    or f"nba-{r.game_date}-{r.home_team_name}-{r.away_team_name}",
                    "league": "NBA",
                    "game_date": r.game_date,
                    "home_team_name": r.home_team_name,
                    "away_team_name": r.away_team_name,
                    "commence_time": to_naive_utc(gl.game_time),
                    "projection_ref": projection_ref(
                        r,
                        game_date=r.game_date,
                        home_team_name=r.home_team_name,
                        away_team_name=r.away_team_name,
                    ),
                    "model_version": getattr(r, "model_version", None),
                    "home_win_prob": r.home_win_prob,
                    "away_win_prob": 1.0 - r.home_win_prob,
                    "model_edge": model_part,
                    "moneyline_home": gl.moneyline_home,
                    "moneyline_away": gl.moneyline_away,
                    "side": "home" if edge > 0 else "away",
                    "confidence_score": r.confidence_score,
                    "generated_at": r.created_at,
                }
            )
        return out
