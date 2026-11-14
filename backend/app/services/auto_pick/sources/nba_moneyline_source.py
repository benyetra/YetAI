"""NBA moneyline source.

No ML recommendation is stored. Pick the side whose model win probability beats
the no-vig implied probability of the two stored moneylines; nothing on no edge.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import NBAGameLines, NBASpreadProjections
from app.services.auto_pick.candidate import DateRange, projection_ref, to_naive_utc

log = logging.getLogger(__name__)


def _implied(american: int) -> float:
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


class NBAMoneylineSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        try:
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
            if edge == 0:
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
                    "moneyline_home": gl.moneyline_home,
                    "moneyline_away": gl.moneyline_away,
                    "side": "home" if edge > 0 else "away",
                    "confidence_score": r.confidence_score,
                    "generated_at": r.created_at,
                }
            )
        return out
