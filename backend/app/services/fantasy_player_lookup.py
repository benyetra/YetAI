"""Resolve Sleeper / GSIS / internal ids to fantasy_players.id for analytics."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.fantasy_models import FantasyPlatform, FantasyPlayer

logger = logging.getLogger(__name__)


def _lookup_by_platform_player_id(db: Session, player_key: str) -> Optional[int]:
    row = db.execute(
        text(
            "SELECT id FROM fantasy_players " "WHERE platform_player_id = :sleeper_id"
        ),
        {"sleeper_id": player_key},
    ).fetchone()
    return int(row[0]) if row else None


def _lookup_by_internal_id(db: Session, player_key: str) -> Optional[int]:
    if not player_key.isdigit():
        return None
    row = db.query(FantasyPlayer.id).filter(FantasyPlayer.id == int(player_key)).first()
    return int(row[0]) if row else None


@lru_cache(maxsize=1)
def _sleeper_to_gsis_map() -> dict[str, str]:
    """Sleeper id -> GSIS id (nflverse import_ids fallback)."""
    try:
        from app.services.etl.fantasy.sync_player_analytics import (
            _load_nflverse_sleeper_to_gsis,
        )

        return _load_nflverse_sleeper_to_gsis()
    except Exception as exc:
        logger.warning("Could not load Sleeper->GSIS map: %s", exc)
        return {}


def _lookup_by_gsis_bridge(db: Session, player_key: str) -> Optional[int]:
    """Map a Sleeper id or GSIS id to fantasy_players.id via GSIS bridge."""
    sleeper_to_gsis = _sleeper_to_gsis_map()
    if not sleeper_to_gsis:
        return None

    target_gsis = (
        player_key if player_key.startswith("00-") else sleeper_to_gsis.get(player_key)
    )
    if not target_gsis:
        return None

    rows = db.execute(
        text(
            "SELECT id, platform_player_id FROM fantasy_players "
            "WHERE platform = :platform"
        ),
        {"platform": FantasyPlatform.SLEEPER.value},
    ).fetchall()

    for fantasy_id, sleeper_id in rows:
        mapped_gsis = sleeper_to_gsis.get(str(sleeper_id))
        if mapped_gsis and str(mapped_gsis) == str(target_gsis):
            return int(fantasy_id)
    return None


def resolve_internal_player_id(db: Session, player_key: str) -> Optional[int]:
    """
    Resolve API player id to internal fantasy_players.id.

    Order: Sleeper platform_player_id, numeric internal id, GSIS bridge.
    """
    key = str(player_key).strip()
    if not key:
        return None

    internal = _lookup_by_platform_player_id(db, key)
    if internal is not None:
        return internal

    internal = _lookup_by_internal_id(db, key)
    if internal is not None:
        return internal

    return _lookup_by_gsis_bridge(db, key)
