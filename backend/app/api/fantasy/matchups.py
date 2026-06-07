"""Matchups, trending, Sleeper test helpers, legacy analytics shims (ojg.2/3)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.services.fantasy_analytics_service import FantasyAnalyticsService
from app.services.fantasy_connection_service import fantasy_connection_service
from app.services.sleeper_fantasy_service import SleeperFantasyService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fantasy"])


def _map_sleeper_to_internal_player_id(
    db: Session, sleeper_player_id: str
) -> Optional[int]:
    row = db.execute(
        text("SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"),
        {"sleeper_id": str(sleeper_player_id)},
    ).fetchone()
    return int(row[0]) if row else None


async def _resolve_user_platform_id(user_id: int) -> Optional[str]:
    connections = await fantasy_connection_service.get_user_connections(user_id)
    for account in connections.get("accounts", []):
        if account.get("platform") == "sleeper" and account.get("platform_user_id"):
            return str(account["platform_user_id"])
    return None


def _build_matchup_status(score1: float, score2: float) -> str:
    if score1 == 0 and score2 == 0:
        return "upcoming"
    if score1 == score2 and score1 > 0:
        return "tied"
    if score1 > 0 or score2 > 0:
        return "completed"
    return "upcoming"


@router.get("/api/fantasy/matchups/{league_id}/{week}")
async def get_fantasy_matchups(
    league_id: str,
    week: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Weekly head-to-head matchups for a Sleeper league."""
    try:
        sleeper = SleeperFantasyService()
        teams = await sleeper.get_league_teams(league_id)
        team_lookup = {str(team.get("team_id")): team for team in teams}
        platform_user_id = await _resolve_user_platform_id(
            current_user.get("id") or current_user.get("user_id")
        )

        raw_matchups = await sleeper.get_league_matchups(league_id, week)
        matchups: List[Dict[str, Any]] = []

        for raw in raw_matchups:
            team1 = team_lookup.get(str(raw.get("team1_id")))
            team2 = team_lookup.get(str(raw.get("team2_id")))
            if not team1 or not team2:
                continue

            score1 = float(raw.get("team1_score", 0))
            score2 = float(raw.get("team2_score", 0))
            is_user_team = lambda team: bool(
                platform_user_id and str(team.get("owner_id")) == platform_user_id
            )

            matchups.append(
                {
                    "matchup_id": str(raw.get("matchup_id")),
                    "week": week,
                    "team1": {
                        "id": int(team1.get("team_id")),
                        "name": team1.get("name"),
                        "owner_name": team1.get("owner_name"),
                        "is_user_team": is_user_team(team1),
                        "score": score1,
                        "starters": raw.get("team1_starters") or [],
                    },
                    "team2": {
                        "id": int(team2.get("team_id")),
                        "name": team2.get("name"),
                        "owner_name": team2.get("owner_name"),
                        "is_user_team": is_user_team(team2),
                        "score": score2,
                        "starters": raw.get("team2_starters") or [],
                    },
                    "status": _build_matchup_status(score1, score2),
                    "user_involved": is_user_team(team1) or is_user_team(team2),
                }
            )

        matchups.sort(key=lambda item: (not item["user_involved"], item["matchup_id"]))

        return {
            "status": "success",
            "matchups": matchups,
            "week": week,
            "league_id": league_id,
            "message": f"Retrieved {len(matchups)} matchups for week {week}",
        }
    except Exception as exc:
        logger.error(
            "Error loading matchups for league %s week %s: %s", league_id, week, exc
        )
        raise HTTPException(
            status_code=500, detail="Failed to fetch league matchups"
        ) from exc


async def _trending_payload(trend_type: str = "add", limit: int = 25) -> Dict[str, Any]:
    sleeper = SleeperFantasyService()
    trending = await sleeper.get_trending_players(trend_type)
    return {
        "status": "success",
        "trending": trending[:limit],
        "trend_type": trend_type,
        "message": f"Retrieved {min(len(trending), limit)} trending players",
    }


@router.get("/api/fantasy/trending")
async def get_fantasy_trending(
    trend_type: str = Query("add", pattern="^(add|drop)$"),
    limit: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """Sleeper trending adds/drops for waiver wire context."""
    return await _trending_payload(trend_type=trend_type, limit=limit)


@router.get("/api/fantasy/test/sleeper-trending")
async def get_fantasy_trending_legacy(
    current_user: dict = Depends(get_current_user),
):
    """Legacy alias for frontend ``getTrendingPlayers``."""
    return await _trending_payload(trend_type="add", limit=25)


@router.get("/api/fantasy/test/sleeper/{username}")
async def test_sleeper_username(
    username: str,
    current_user: dict = Depends(get_current_user),
):
    """Validate a Sleeper username resolves before connect."""
    sleeper = SleeperFantasyService()
    try:
        user = await sleeper.authenticate_user({"username": username})
        return {
            "status": "success",
            "username": username,
            "sleeper_user_id": user.get("user_id"),
            "display_name": user.get("display_name") or user.get("username"),
            "message": "Sleeper user found",
        }
    except Exception as exc:
        logger.warning("Sleeper test lookup failed for %s: %s", username, exc)
        raise HTTPException(status_code=404, detail="Sleeper user not found") from exc


@router.get("/api/fantasy/analytics/breakout-candidates/{position}")
async def get_breakout_candidates_legacy(
    position: str,
    season: int = Query(2025, ge=2000, le=2100),
    min_weeks: int = Query(3, ge=1, le=16),
    limit: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy shim for frontend breakout analytics."""
    del season, min_weeks
    analytics_service = FantasyAnalyticsService(db)
    candidates = analytics_service.get_breakout_candidates(position.upper(), limit)
    return {
        "status": "success",
        "candidates": candidates,
        "position": position.upper(),
    }


@router.get("/api/fantasy/analytics/{player_id}/matchup/{opponent}")
async def get_matchup_analytics_legacy(
    player_id: str,
    opponent: str,
    season: int = Query(2025, ge=2000, le=2100),
    week: int = Query(1, ge=1, le=22),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy shim for frontend matchup analytics."""
    del season
    internal_id = _map_sleeper_to_internal_player_id(db, player_id)
    if internal_id is None:
        return {
            "status": "error",
            "message": f"Player not found with ID: {player_id}",
            "matchup": {},
        }

    analytics_service = FantasyAnalyticsService(db)
    analysis = analytics_service.get_matchup_analysis(
        internal_id, opponent.upper(), week
    )
    if "error" in analysis:
        return {"status": "error", "message": analysis["error"], "matchup": {}}

    return {"status": "success", "matchup": analysis, "player_id": player_id}
