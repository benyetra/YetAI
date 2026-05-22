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


# YetAIBet.bet_type uses BetType enum ("moneyline", "spread", "total", "prop").
# Candidates use MarketType ("moneyline", "spread", "total", "player_prop").
# Only "prop" / "player_prop" differs; everything else aligns.
_BET_TYPE_TO_MARKET_TYPE = {
    "moneyline": "moneyline",
    "spread": "spread",
    "total": "total",
    "prop": "player_prop",
}

# YetAIBet.sport uses Odds-API style strings ("basketball_nba", "baseball_mlb").
# Source shims emit short league strings ("NBA", "MLB"). Normalize sport -> league
# so the scorer lookup hits.
_SPORT_TO_LEAGUE = {
    "basketball_nba": "NBA",
    "basketball_wnba": "WNBA",
    "baseball_mlb": "MLB",
    "icehockey_nhl": "NHL",
    "americanfootball_nfl": "NFL",
    "americanfootball_ncaaf": "NCAAF",
    "basketball_ncaab": "NCAAB",
}


def _normalize_market_type(bet_type_value: str) -> str:
    return _BET_TYPE_TO_MARKET_TYPE.get(bet_type_value, bet_type_value)


def _normalize_sport(sport_value: str) -> str:
    return _SPORT_TO_LEAGUE.get(sport_value, sport_value)


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

    Keys are normalized to match what candidates emit:
    - BetType -> MarketType ("prop" -> "player_prop"; others unchanged)
    - Odds-API sport string -> short league code ("basketball_nba" -> "NBA")

    Result key: (market_type_str, league_str) — e.g. ("player_prop", "NBA").
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
            raw_market = str(row.bet_type.value if hasattr(row.bet_type, "value") else row.bet_type)
            raw_sport = str(row.sport or "unknown")
            key = (_normalize_market_type(raw_market), _normalize_sport(raw_sport))
            hit_rates[key] = (row.wins or 0) / row.total

    return hit_rates


def _load_line_movement(db: Session, now: datetime) -> dict[str, dict]:
    """Return line-movement data keyed by event_id.

    OddsHistory stores point-in-time snapshots but lacks opened_line / current_line /
    side columns required by line_movement_sub_score. Returning {} here is safe:
    line_movement_sub_score already returns the neutral score (50) when an event_id
    is absent. Wire this up once an odds-movement pipeline populates the needed fields.
    """
    return {}
