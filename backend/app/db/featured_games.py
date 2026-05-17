"""Featured games table helpers (admin-curated dashboard games)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

FEATURED_GAMES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS featured_games (
    id SERIAL PRIMARY KEY,
    game_id VARCHAR(255) NOT NULL,
    home_team VARCHAR(255) NOT NULL,
    away_team VARCHAR(255) NOT NULL,
    start_time TIMESTAMP NOT NULL,
    sport_key VARCHAR(100) NOT NULL DEFAULT 'americanfootball_nfl',
    explanation TEXT NOT NULL DEFAULT '',
    admin_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def ensure_featured_games_table(db: Session) -> None:
    """Create featured_games if missing. Safe to call on every request."""
    db.execute(text(FEATURED_GAMES_TABLE_SQL))
    db.commit()


def format_start_time_iso(start_time: Any) -> Optional[str]:
    if not start_time:
        return None
    if isinstance(start_time, datetime):
        if start_time.tzinfo is None:
            return start_time.replace(tzinfo=timezone.utc).isoformat()
        return start_time.astimezone(timezone.utc).isoformat()
    return str(start_time)


def row_to_featured_game(row: Any, *, include_admin_notes: bool = False) -> dict:
    payload = {
        "id": row.game_id,
        "game_id": row.game_id,
        "home_team": row.home_team,
        "away_team": row.away_team,
        "start_time": format_start_time_iso(row.start_time),
        "commence_time": format_start_time_iso(row.start_time),
        "sport_key": row.sport_key,
        "status": "scheduled",
        "explanation": row.explanation,
    }
    if include_admin_notes:
        payload["admin_notes"] = getattr(row, "admin_notes", None)
    return payload
