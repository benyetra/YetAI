"""Resolve Sleeper or internal IDs for trade analyzer player lookups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

from sqlalchemy.orm import Session

from app.models.fantasy_models import FantasyPlatform, FantasyPlayer


@dataclass
class ResolvedTradePlayer:
    """Unified player metadata for trade evaluation."""

    sleeper_id: str
    internal_id: Optional[int]
    name: str
    position: str
    team: str
    age: Optional[int]
    fantasy_player: Optional[FantasyPlayer]
    injury_status: Optional[str] = None

    @property
    def position_key(self) -> str:
        pos = self.position or "UNKNOWN"
        if hasattr(pos, "value"):
            return str(pos.value)
        return str(pos)


def resolve_trade_player(
    db: Session, player_id: Union[int, str]
) -> Optional[ResolvedTradePlayer]:
    """Resolve a trade asset player id (internal DB or Sleeper platform id)."""
    player_key = str(player_id).strip()
    if not player_key:
        return None

    fantasy_player: Optional[FantasyPlayer] = None

    if player_key.isdigit():
        fantasy_player = (
            db.query(FantasyPlayer).filter(FantasyPlayer.id == int(player_key)).first()
        )

    if fantasy_player is None:
        fantasy_player = (
            db.query(FantasyPlayer)
            .filter(
                FantasyPlayer.platform == FantasyPlatform.SLEEPER,
                FantasyPlayer.platform_player_id == player_key,
            )
            .first()
        )

    if fantasy_player:
        sleeper_id = str(fantasy_player.platform_player_id or player_key)
        return ResolvedTradePlayer(
            sleeper_id=sleeper_id,
            internal_id=int(fantasy_player.id),
            name=str(fantasy_player.name or f"Player {sleeper_id}"),
            position=str(fantasy_player.position or "UNKNOWN"),
            team=str(fantasy_player.team or ""),
            age=fantasy_player.age,
            fantasy_player=fantasy_player,
            injury_status=fantasy_player.injury_description,
        )

    try:
        from app.models.database_models import SleeperPlayer

        sleeper_row = (
            db.query(SleeperPlayer)
            .filter(SleeperPlayer.sleeper_player_id == player_key)
            .first()
        )
        if sleeper_row:
            return ResolvedTradePlayer(
                sleeper_id=player_key,
                internal_id=None,
                name=str(
                    getattr(sleeper_row, "full_name", None)
                    or getattr(sleeper_row, "name", None)
                    or f"Player {player_key}"
                ),
                position=str(getattr(sleeper_row, "position", None) or "UNKNOWN"),
                team=str(getattr(sleeper_row, "team", None) or ""),
                age=getattr(sleeper_row, "age", None),
                fantasy_player=None,
                injury_status=getattr(sleeper_row, "injury_status", None),
            )
    except Exception:
        pass

    return None
