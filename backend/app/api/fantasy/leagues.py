"""
Fantasy API routes (extracted from main.py — ojg.9).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.service_loader import get_service, is_service_available

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fantasy"])


@router.get("/api/fantasy/leagues/{league_id}/rules")
async def get_league_rules(
    league_id: str, current_user: dict = Depends(get_current_user)
):
    """Get fantasy league rules and settings"""
    try:
        from app.services.fantasy_league_format import league_format_flags_from_sleeper
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get detailed league information
        league_details = await sleeper_service.get_league_details(league_id)

        # Get the actual roster count from teams data
        teams_count = len(league_details.get("teams", []))

        # If teams count is 0, try to get it from the raw league data
        if teams_count == 0:
            # Make a direct API call to get league info
            import httpx

            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(
                        f"https://api.sleeper.app/v1/league/{league_id}"
                    )
                    if response.status_code == 200:
                        raw_league_data = response.json()
                        teams_count = raw_league_data.get("total_rosters", 0)
                        # Update league_details with missing data
                        league_details.update(raw_league_data)
                except Exception as e:
                    logger.warning(f"Could not fetch additional league data: {e}")

        # Get the raw scoring settings from Sleeper
        raw_scoring = league_details.get("scoring_settings", {})

        # Structure the scoring settings to match frontend expectations
        structured_scoring = {
            "passing": {
                "touchdowns": raw_scoring.get("pass_td", 6),
                "yards_per_point": (
                    1.0 / raw_scoring.get("pass_yd", 25)
                    if raw_scoring.get("pass_yd", 0) > 0
                    else 0
                ),
                "interceptions": raw_scoring.get("pass_int", -2),
            },
            "rushing": {
                "touchdowns": raw_scoring.get("rush_td", 6),
                "yards_per_point": (
                    1.0 / raw_scoring.get("rush_yd", 10)
                    if raw_scoring.get("rush_yd", 0) > 0
                    else 0
                ),
                "fumbles": raw_scoring.get("fum_lost", -2),
            },
            "receiving": {
                "touchdowns": raw_scoring.get("rec_td", 6),
                "yards_per_point": (
                    1.0 / raw_scoring.get("rec_yd", 10)
                    if raw_scoring.get("rec_yd", 0) > 0
                    else 0
                ),
                "receptions": raw_scoring.get("rec", 1),
                "fumbles": raw_scoring.get("fum_lost", -2),
            },
            "kicking": {
                "field_goals": raw_scoring.get("fgm", 3),
                "extra_points": raw_scoring.get("xpm", 1),
                "field_goal_misses": raw_scoring.get("fgmiss", 0),
            },
            "defense": {
                "sacks": raw_scoring.get("sack", 1),
                "interceptions": raw_scoring.get("def_int", 2),
                "fumble_recoveries": raw_scoring.get("fum_rec", 2),
                "touchdowns": raw_scoring.get("def_td", 6),
            },
            "special_scoring": [],  # Add empty special scoring to prevent frontend error
        }

        # Get roster positions and calculate roster info
        roster_positions = league_details.get("roster_positions", [])
        starting_positions = [
            pos for pos in roster_positions if pos not in ["BN", "IR"]
        ]
        bench_positions = [pos for pos in roster_positions if pos in ["BN", "IR"]]

        # Use the calculated teams count
        total_rosters = teams_count
        roster_size_label = (
            f"{total_rosters}-Team League" if total_rosters > 0 else "Standard League"
        )

        sleeper_league_doc = {
            "settings": league_details.get("settings")
            or (league_details.get("league_data") or {}).get("settings")
            or {},
            "roster_positions": roster_positions,
            "scoring_settings": raw_scoring,
            "total_rosters": total_rosters,
        }
        format_flags = league_format_flags_from_sleeper(sleeper_league_doc)
        format_type = format_flags["format_type"]
        format_label = format_type.replace("_", " ").title()

        # Count position requirements
        position_counts = {}
        for pos in starting_positions:
            position_counts[pos] = position_counts.get(pos, 0) + 1

        # Build position requirements text
        position_requirements = []
        for pos, count in position_counts.items():
            if count > 1:
                position_requirements.append(f"{count} {pos}")
            else:
                position_requirements.append(pos)

        # Extract rules and settings from league details
        rules = {
            "league_name": league_details.get("name", "Unknown League"),
            "league_type": roster_size_label,
            "format_type": format_type,
            "format_label": format_label,
            "is_dynasty": format_flags["is_dynasty"],
            "is_keeper": format_flags["is_keeper"],
            "is_redraft": format_flags["is_redraft"],
            "total_rosters": total_rosters,
            "teams_count": total_rosters,
            "platform": "Sleeper",
            "scoring_type": structured_scoring.get("receiving", {}).get("receptions", 0)
            > 0
            and "PPR"
            or "Standard",
            "roster_positions": roster_positions,
            "scoring_settings": structured_scoring,
            "waiver_settings": {
                "waiver_type": league_details.get("waiver_type", "waiver_priority"),
                "waiver_budget": league_details.get("waiver_budget", 100),
                "waiver_clear_days": league_details.get("waiver_clear_days", 1),
                **league_details.get("waiver_settings", {}),
            },
            "playoff_settings": {
                "playoff_week_start": league_details.get("playoff_week_start", 15),
                "playoff_teams": league_details.get("playoff_teams", 4),
                "playoff_rounds": league_details.get("playoff_rounds", 2),
            },
            "draft_settings": {
                "draft_type": league_details.get("draft_type", "snake"),
                "draft_order": league_details.get("draft_order"),
                "draft_rounds": league_details.get(
                    "draft_rounds", len(roster_positions)
                ),
            },
            "roster_config": {
                "total_spots": len(roster_positions),
                "starting_spots": len(starting_positions),
                "bench_spots": len(bench_positions),
                "starting_lineup": starting_positions,
                "bench_lineup": bench_positions,
            },
            "position_requirements": position_requirements,
            "league_features": {
                "trade_deadline": league_details.get("trade_deadline"),
                "taxi_slots": league_details.get("taxi_slots", 0),
                "reserve_slots": league_details.get("reserve_slots", 0),
                "waiver_type": league_details.get("waiver_type", "waiver_priority"),
                "daily_waivers": league_details.get("daily_waivers", False),
                "dynasty": format_flags["is_dynasty"],
                "keeper": format_flags["is_keeper"],
            },
            "settings": sleeper_league_doc.get("settings") or {},
            "season": league_details.get("season", "2024"),
            "status": league_details.get("status", "pre_draft"),
        }

        return {
            "status": "success",
            "rules": rules,
            "message": f"Retrieved rules for league {league_details.get('name', league_id)}",
        }
    except Exception as e:
        logger.error(f"Error getting rules for league {league_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get league rules")


@router.delete("/api/fantasy/leagues/{league_id}")
async def delete_fantasy_league(
    league_id: str, current_user: dict = Depends(get_current_user)
):
    """Remove a fantasy league from the user's YetAI account."""
    try:
        from app.services.fantasy_sleeper_unified import fantasy_sleeper_unified

        result = await fantasy_sleeper_unified.disconnect_league(
            current_user["user_id"], league_id
        )
        if result.get("status") != "success":
            raise HTTPException(
                status_code=404,
                detail=result.get("message", "Failed to delete fantasy league"),
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting league {league_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete fantasy league")
