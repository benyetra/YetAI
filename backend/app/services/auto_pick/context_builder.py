"""
Context builder for auto-pick scoring.

Assembles a ScoringContext from DB inputs at orchestrator start.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.database_models import YetAIBet
from app.services.auto_pick.config_loader import LoadedScoringConfig
from app.services.auto_pick.scoring_context import ScoringContext

logger = logging.getLogger(__name__)


def build_scoring_context(
    db: Session, cfg: LoadedScoringConfig, now: datetime
) -> ScoringContext:
    return ScoringContext(
        weights=cfg.weights,
        score_threshold=cfg.score_threshold,
        historical_hit_rates=_load_historical_hit_rates(db, now),
        line_movement=_load_line_movement(db, now),
        now=now,
    )


def _load_historical_hit_rates(
    db: Session, now: datetime
) -> dict[tuple[str, str], float]:
    """90-day rolling hit rate from settled YetAIBet, grouped by (bet_type, sport).

    Returns {} if no settled data; logs a warning so operators know context is cold.
    Key: (market_type_str, sport_str) — e.g. ("moneyline", "basketball_nba").
    """
    cutoff = now - timedelta(days=90)

    rows = (
        db.query(
            YetAIBet.bet_type,
            YetAIBet.sport,
            func.count(YetAIBet.id).label("total"),
            func.sum(case((YetAIBet.result == "won", 1), else_=0)).label("wins"),
        )
        .filter(
            YetAIBet.status == "settled",
            YetAIBet.settled_at >= cutoff,
            YetAIBet.result.in_(["won", "lost"]),
        )
        .group_by(YetAIBet.bet_type, YetAIBet.sport)
        .all()
    )

    if not rows:
        logger.warning(
            "context_builder: no settled YetAIBet data in the last 90 days — "
            "historical_hit_rates will be empty (neutral scoring)."
        )
        return {}

    hit_rates: dict[tuple[str, str], float] = {}
    for row in rows:
        if row.total and row.total > 0:
            market = str(row.bet_type.value if hasattr(row.bet_type, "value") else row.bet_type)
            sport = str(row.sport or "unknown")
            hit_rates[(market, sport)] = (row.wins or 0) / row.total

    return hit_rates


def _load_line_movement(db: Session, now: datetime) -> dict[str, dict]:
    """Return line-movement data keyed by event_id.

    OddsHistory stores point-in-time snapshots but lacks opened_line / current_line /
    side columns required by line_movement_sub_score. Returning {} here is safe:
    line_movement_sub_score already returns the neutral score (50) when an event_id
    is absent. Wire this up once an odds-movement pipeline populates the needed fields.
    """
    return {}
