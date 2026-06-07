"""
Canonical Sleeper fantasy integration.

All Sleeper connect/sync/league flows should go through this module.
Legacy ``SimplifiedSleeperService`` and ``/api/sleeper/*`` routes delegate here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.database_models import User
from app.models.fantasy_models import (
    FantasyLeague,
    FantasyLeagueType,
    FantasyPlatform,
    FantasyPlayer,
    FantasyPosition,
    FantasyUser,
    PlayerStatus,
)
from app.services.sleeper_fantasy_service import SleeperFantasyService

logger = logging.getLogger(__name__)

_FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def _safe_int(value: Any) -> Optional[int]:
    """Coerce Sleeper numeric fields; empty strings become None."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_fantasy_position(position: Optional[str]) -> FantasyPosition:
    if position in _FANTASY_POSITIONS:
        return FantasyPosition(position)
    return FantasyPosition.BENCH


def _parse_player_status(status: Optional[str]) -> PlayerStatus:
    if not status:
        return PlayerStatus.ACTIVE
    normalized = status.lower()
    mapping = {
        "active": PlayerStatus.ACTIVE,
        "inactive": PlayerStatus.OUT,
        "injured reserve": PlayerStatus.OUT,
        "ir": PlayerStatus.OUT,
        "out": PlayerStatus.OUT,
        "doubtful": PlayerStatus.DOUBTFUL,
        "questionable": PlayerStatus.QUESTIONABLE,
        "probable": PlayerStatus.PROBABLE,
    }
    return mapping.get(normalized, PlayerStatus.ACTIVE)


class FantasySleeperUnifiedService:
    """Single integration point for Sleeper + FantasyUser persistence."""

    def __init__(self) -> None:
        self.sleeper = SleeperFantasyService()

    def _mirror_user_sleeper_id(
        self, db: Session, user_id: int, platform_user_id: str
    ) -> None:
        user = db.query(User).filter(User.id == user_id).first()
        if user is not None:
            user.sleeper_user_id = platform_user_id

    async def connect(
        self, user_id: int, username: str, db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """Connect Sleeper account via FantasyUser (canonical store)."""
        owns_session = db is None
        db = db or SessionLocal()
        try:
            sleeper_user = await self.sleeper.authenticate_user({"username": username})
            platform_user_id = sleeper_user["user_id"]

            connection = (
                db.query(FantasyUser)
                .filter(
                    FantasyUser.user_id == user_id,
                    FantasyUser.platform == FantasyPlatform.SLEEPER,
                )
                .first()
            )

            is_new = connection is None
            if connection is None:
                connection = FantasyUser(
                    user_id=user_id,
                    platform=FantasyPlatform.SLEEPER,
                    platform_user_id=platform_user_id,
                    platform_username=sleeper_user["username"],
                    is_active=True,
                )
                db.add(connection)
            else:
                connection.platform_user_id = platform_user_id
                connection.platform_username = sleeper_user["username"]
                connection.is_active = True
                connection.sync_error = None
                connection.updated_at = datetime.now(timezone.utc)

            self._mirror_user_sleeper_id(db, user_id, platform_user_id)
            db.commit()
            db.refresh(connection)

            return {
                "status": "success",
                "connection": {
                    "platform": "sleeper",
                    "platform_user_id": platform_user_id,
                    "platform_username": sleeper_user["username"],
                    "display_name": sleeper_user.get(
                        "display_name", sleeper_user["username"]
                    ),
                    "connected_at": (
                        connection.created_at.isoformat()
                        if connection.created_at
                        else datetime.now(timezone.utc).isoformat()
                    ),
                    "is_new_connection": is_new,
                },
                "message": (
                    "Successfully connected to Sleeper"
                    if is_new
                    else "Successfully updated Sleeper connection"
                ),
                "sleeper_user_id": platform_user_id,
                "username": sleeper_user["username"],
            }
        except Exception:
            db.rollback()
            raise
        finally:
            if owns_session:
                db.close()

    def get_connections(
        self, user_id: int, db: Optional[Session] = None
    ) -> Dict[str, Any]:
        owns_session = db is None
        db = db or SessionLocal()
        try:
            connections = (
                db.query(FantasyUser)
                .filter(FantasyUser.user_id == user_id, FantasyUser.is_active.is_(True))
                .all()
            )
            accounts = [
                {
                    "id": conn.platform_user_id,
                    "platform": conn.platform.value,
                    "platform_user_id": conn.platform_user_id,
                    "platform_username": conn.platform_username,
                    "user_id": conn.platform_user_id,
                    "username": conn.platform_username,
                    "connected_at": (
                        conn.created_at.isoformat() if conn.created_at else None
                    ),
                    "last_sync": conn.last_sync.isoformat() if conn.last_sync else None,
                    "status": "active",
                }
                for conn in connections
            ]
            return {
                "status": "success",
                "accounts": accounts,
                "message": f"Found {len(accounts)} active fantasy connections",
            }
        finally:
            if owns_session:
                db.close()

    async def get_leagues(
        self, user_id: int, db: Optional[Session] = None
    ) -> Dict[str, Any]:
        owns_session = db is None
        db = db or SessionLocal()
        try:
            connections = (
                db.query(FantasyUser)
                .filter(FantasyUser.user_id == user_id, FantasyUser.is_active.is_(True))
                .all()
            )
            all_leagues: List[Dict[str, Any]] = []
            for connection in connections:
                if connection.platform != FantasyPlatform.SLEEPER:
                    continue
                leagues = await self.sleeper.get_user_leagues(
                    connection.platform_user_id
                )
                for league in leagues:
                    league["platform"] = "sleeper"
                    league["fantasy_user_id"] = connection.id
                    league["platform_user_id"] = connection.platform_user_id
                    league["id"] = league.get("league_id", league.get("id"))
                all_leagues.extend(leagues)
            return {
                "status": "success",
                "leagues": all_leagues,
                "message": f"Found {len(all_leagues)} fantasy leagues",
            }
        finally:
            if owns_session:
                db.close()

    async def sync_league(
        self,
        user_id: int,
        league_id: str,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Refresh a league from Sleeper and persist FantasyLeague metadata."""
        owns_session = db is None
        db = db or SessionLocal()
        try:
            connection = (
                db.query(FantasyUser)
                .filter(
                    FantasyUser.user_id == user_id,
                    FantasyUser.platform == FantasyPlatform.SLEEPER,
                    FantasyUser.is_active.is_(True),
                )
                .first()
            )
            if connection is None:
                raise ValueError("Connect a Sleeper account before syncing leagues")

            league_details = await self.sleeper.get_league_details(league_id)
            league_data = league_details.get("league_data", league_details)
            season = int(league_data.get("season") or datetime.now().year)
            name = league_data.get("name") or league_details.get("name") or league_id

            existing = (
                db.query(FantasyLeague)
                .filter(
                    FantasyLeague.fantasy_user_id == connection.id,
                    FantasyLeague.platform_league_id == str(league_id),
                )
                .first()
            )
            if existing is None:
                existing = FantasyLeague(
                    fantasy_user_id=connection.id,
                    platform=FantasyPlatform.SLEEPER,
                    platform_league_id=str(league_id),
                    name=name,
                    season=season,
                )
                db.add(existing)

            existing.name = name
            existing.season = season
            existing.team_count = league_data.get(
                "total_rosters"
            ) or league_details.get("team_count")
            existing.scoring_type = league_details.get("scoring_type")
            existing.roster_positions = league_details.get("roster_positions")
            existing.last_sync = datetime.now(timezone.utc)
            existing.is_synced = True

            connection.last_sync = datetime.now(timezone.utc)
            connection.sync_error = None
            db.commit()

            return {
                "status": "success",
                "league_id": str(league_id),
                "name": name,
                "season": season,
                "last_sync": existing.last_sync.isoformat(),
                "message": f"Synced league {name}",
            }
        except Exception as exc:
            db.rollback()
            logger.error(
                "Failed syncing league %s for user %s: %s", league_id, user_id, exc
            )
            raise
        finally:
            if owns_session:
                db.close()

    async def sync_all_leagues(
        self, user_id: int, db: Optional[Session] = None
    ) -> Dict[str, Any]:
        leagues_response = await self.get_leagues(user_id, db=db)
        synced = 0
        for league in leagues_response.get("leagues", []):
            league_id = league.get("league_id") or league.get("id")
            if not league_id:
                continue
            await self.sync_league(user_id, str(league_id), db=db)
            synced += 1
        return {
            "status": "success",
            "total_synced": synced,
            "message": f"Synced {synced} leagues",
        }

    async def sync_fantasy_players(self, db: Session) -> Dict[str, Any]:
        """Upsert ``fantasy_players`` rows from Sleeper's player catalog."""
        players_data = await self.sleeper._get_all_players()
        created = 0
        updated = 0

        for sleeper_id, player_data in players_data.items():
            position = player_data.get("position")
            if position not in _FANTASY_POSITIONS:
                continue
            if not player_data.get("active"):
                continue

            name = (
                f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}"
            ).strip()
            if not name:
                continue

            existing = (
                db.query(FantasyPlayer)
                .filter(
                    FantasyPlayer.platform == FantasyPlatform.SLEEPER,
                    FantasyPlayer.platform_player_id == str(sleeper_id),
                )
                .first()
            )
            payload = {
                "name": name,
                "position": _parse_fantasy_position(position),
                "team": _optional_str(player_data.get("team")),
                "age": _safe_int(player_data.get("age")),
                "height": _optional_str(player_data.get("height")),
                "weight": _safe_int(player_data.get("weight")),
                "college": _optional_str(player_data.get("college")),
                "experience": _safe_int(player_data.get("years_exp")),
                "status": _parse_player_status(player_data.get("injury_status")),
                "injury_description": _optional_str(
                    player_data.get("injury_body_part")
                ),
                "updated_at": datetime.now(timezone.utc),
            }

            if existing is None:
                db.add(
                    FantasyPlayer(
                        platform=FantasyPlatform.SLEEPER,
                        platform_player_id=str(sleeper_id),
                        **payload,
                    )
                )
                created += 1
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                updated += 1

        db.commit()
        return {
            "created": created,
            "updated": updated,
            "total_processed": created + updated,
        }

    async def get_sync_status(self, user_id: int, db: Session) -> Dict[str, Any]:
        connection = (
            db.query(FantasyUser)
            .filter(
                FantasyUser.user_id == user_id,
                FantasyUser.platform == FantasyPlatform.SLEEPER,
                FantasyUser.is_active.is_(True),
            )
            .first()
        )
        user = db.query(User).filter(User.id == user_id).first()
        league_count = (
            db.query(FantasyLeague)
            .join(FantasyUser)
            .filter(FantasyUser.user_id == user_id, FantasyLeague.is_synced.is_(True))
            .count()
        )
        player_count = (
            db.query(FantasyPlayer)
            .filter(FantasyPlayer.platform == FantasyPlatform.SLEEPER)
            .count()
        )

        return {
            "sleeper_connected": connection is not None,
            "sleeper_user_id": user.sleeper_user_id if user else None,
            "platform_username": connection.platform_username if connection else None,
            "leagues_synced": league_count,
            "fantasy_players": player_count,
            "last_sync": (
                connection.last_sync.isoformat()
                if connection and connection.last_sync
                else None
            ),
        }

    async def get_league_rosters_from_sleeper(
        self, league_id: str
    ) -> List[Dict[str, Any]]:
        standings = await self.sleeper.get_league_standings(league_id)
        rosters: List[Dict[str, Any]] = []
        for team in standings:
            rosters.append(
                {
                    "sleeper_roster_id": team.get("roster_id"),
                    "sleeper_owner_id": team.get("owner_id"),
                    "team_name": team.get("name"),
                    "owner_name": team.get("owner_name"),
                    "wins": team.get("wins", 0),
                    "losses": team.get("losses", 0),
                    "ties": team.get("ties", 0),
                    "points_for": team.get("points_for", 0),
                    "points_against": team.get("points_against", 0),
                    "waiver_position": team.get("waiver_position"),
                    "player_count": team.get("player_count", 0),
                }
            )
        return rosters

    async def disconnect(self, user_id: int, platform_user_id: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            connection = (
                db.query(FantasyUser)
                .filter(
                    FantasyUser.user_id == user_id,
                    FantasyUser.platform_user_id == platform_user_id,
                    FantasyUser.is_active.is_(True),
                )
                .first()
            )
            if connection is None:
                return {"status": "error", "message": "Fantasy connection not found"}

            connection.is_active = False
            connection.updated_at = datetime.now(timezone.utc)

            user = db.query(User).filter(User.id == user_id).first()
            if user and user.sleeper_user_id == platform_user_id:
                user.sleeper_user_id = None

            db.commit()
            return {
                "status": "success",
                "message": "Successfully disconnected Sleeper account",
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


fantasy_sleeper_unified = FantasySleeperUnifiedService()
