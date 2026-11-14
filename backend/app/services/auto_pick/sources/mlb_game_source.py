"""
MLB game moneyline source (GameProjections).

``ml_recommendation`` is HOME / AWAY / NO_PLAY (etl/mlb/game_projection_pipeline.py);
NO_PLAY, missing prices or a missing price for the picked side are skipped.
``game_time`` is the statsapi UTC start (stored as naive UTC).

MLBGameTotalsSource is intentionally not provided: GameProjections stores
``market_total`` but no over/under price, and no other table has one.
"""

import logging

from sqlalchemy.orm import Session

from app.models.predictions_models import GameProjections
from app.services.auto_pick.candidate import DateRange, projection_ref, to_naive_utc

log = logging.getLogger(__name__)


class MLBGameMoneylineSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date
        try:
            rows = (
                self.db.query(GameProjections).filter(GameProjections.date == day).all()
            )
        except Exception:
            log.exception("MLBGameMoneylineSource: DB query failed")
            return []

        out: list[dict] = []
        for r in rows:
            rec = (r.ml_recommendation or "").strip().upper()
            if rec not in ("HOME", "AWAY"):
                continue
            if r.market_home_ml is None or r.market_away_ml is None:
                continue
            out.append(
                {
                    "event_id": f"mlb-{day}-{r.game_id}",
                    "league": "MLB",
                    "game_date": day,
                    "home_team_name": r.home_team,
                    "away_team_name": r.away_team,
                    "projection_ref": projection_ref(r, date=day, game_id=r.game_id),
                    "model_version": getattr(r, "model_version", None),
                    "side": rec.lower(),
                    "home_win_prob": float(r.home_win_prob),
                    "away_win_prob": float(r.away_win_prob),
                    "moneyline_home": int(r.market_home_ml),
                    "moneyline_away": int(r.market_away_ml),
                    "model_confidence": r.model_confidence,
                    "confidence_score": r.model_confidence,
                    "generated_at": r.updated_at or r.created_at,
                    "commence_time": to_naive_utc(r.game_time),
                }
            )
        return out
