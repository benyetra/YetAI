"""Pydantic models for fantasy API routes."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class FantasyConnectRequest(BaseModel):
    platform: str
    credentials: Dict[str, Any]


class ComparePlayersRequest(BaseModel):
    player_ids: List[str]
    league_id: Optional[str] = None
