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


@router.get("/api/fantasy/recommendations/start-sit/{week}")
async def get_start_sit_recommendations(
    week: int,
    league_id: Optional[str] = Query(
        None, description="Optional Sleeper league id; omit for all connected leagues"
    ),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get start/sit recommendations for a given week based on user's actual roster"""
    try:
        from app.services.fantasy_connection_service import fantasy_connection_service
        from app.services.sleeper_fantasy_service import SleeperFantasyService
        from app.services.player_analytics_service import PlayerAnalyticsService
        from app.services.start_sit_service import (
            filter_leagues_for_start_sit,
            find_user_team_in_standings,
            resolve_platform_user_id,
        )
        from sqlalchemy import text

        sleeper_service = SleeperFantasyService()
        analytics_service = PlayerAnalyticsService(db)

        def calculate_confidence(game_points, total_games, position):
            """Calculate confidence based on data quality, consistency, and sample size"""
            if not game_points:
                return 50

            # Base confidence starts with sample size
            if len(game_points) >= 3:
                base_confidence = 85
            elif len(game_points) == 2:
                base_confidence = 75
            else:
                base_confidence = 65

            # Adjust for consistency (lower variance = higher confidence)
            if len(game_points) > 1:
                import statistics

                mean_points = statistics.mean(game_points)
                if mean_points > 0:
                    variance = statistics.stdev(game_points)
                    consistency_factor = max(0, 1 - (variance / mean_points))
                    consistency_adjustment = consistency_factor * 10  # Up to +10 points
                else:
                    consistency_adjustment = -10  # Penalize zero averages
            else:
                consistency_adjustment = 0

            # Adjust for total sample size (more games = higher confidence)
            sample_size_bonus = min(5, total_games - 3)  # Up to +5 for 8+ games

            # Position-specific adjustments
            position_modifiers = {
                "QB": 5,  # QBs are more predictable
                "K": 0,  # Kickers are less predictable
                "DEF": -5,  # Defenses are least predictable
                "RB": 2,  # RBs moderately predictable
                "WR": 0,  # WRs baseline
                "TE": -2,  # TEs slightly less predictable
            }
            position_adjustment = position_modifiers.get(position, 0)

            # Calculate final confidence
            final_confidence = (
                base_confidence
                + consistency_adjustment
                + sample_size_bonus
                + position_adjustment
            )

            # Clamp between 35% and 95%
            return int(max(35, min(95, final_confidence)))

        # Get user's connected leagues
        user_leagues = await fantasy_connection_service.get_user_leagues(
            current_user.get("id") or current_user.get("user_id")
        )

        if not user_leagues.get("leagues"):
            return {
                "status": "success",
                "recommendations": [],
                "message": "No connected fantasy leagues found",
            }

        recommendations = []
        leagues_to_process = filter_leagues_for_start_sit(
            user_leagues["leagues"], league_id
        )

        if league_id and not leagues_to_process:
            return {
                "status": "success",
                "recommendations": [],
                "message": f"League {league_id} not found among connected leagues",
            }

        # Process each connected league (or the one requested via league_id)
        for league in leagues_to_process:
            try:
                current_league_id = league.get("league_id") or league.get("id")
                logger.info(
                    f"Processing league: {current_league_id}, name: {league.get('name')}"
                )
                if not current_league_id:
                    logger.warning("No league_id found, skipping league")
                    continue

                platform_user_id = resolve_platform_user_id(league)
                if not platform_user_id:
                    logger.warning(
                        "No platform_user_id on league %s, skipping",
                        current_league_id,
                    )
                    continue

                league_standings = await sleeper_service.get_league_standings(
                    current_league_id
                )
                logger.info(f"League standings: {len(league_standings)} teams")

                user_team = find_user_team_in_standings(
                    league_standings, platform_user_id
                )
                if not user_team:
                    logger.warning(
                        "No roster found for Sleeper user %s in league %s",
                        platform_user_id,
                        current_league_id,
                    )
                    continue

                # Get user's roster using owner_id
                owner_id = user_team.get("owner_id")
                logger.info(f"Getting roster for owner_id: {owner_id}")
                team_roster_ids = await sleeper_service.get_roster_by_owner(
                    current_league_id, owner_id
                )
                logger.info(f"Team roster player IDs: {team_roster_ids}")

                if not team_roster_ids:
                    logger.warning("No team roster found")
                    continue

                # Get player details for each roster player
                sleeper_players = await sleeper_service._get_all_players()
                team_roster = []
                for player_id in team_roster_ids:
                    if player_id in sleeper_players:
                        player_data = sleeper_players[player_id]
                        team_roster.append(
                            {
                                "player_id": player_id,
                                "name": f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip(),
                                "position": player_data.get("position"),
                                "team": player_data.get("team"),
                                "fantasy_positions": player_data.get(
                                    "fantasy_positions", []
                                ),
                                "injury_status": player_data.get("injury_status"),
                                "status": player_data.get("status"),
                            }
                        )

                logger.info(f"Processed team roster: {len(team_roster)} players")

                if not team_roster:
                    logger.warning("No team roster found")
                    continue

                # Get league roster rules for proper START/SIT decisions
                from app.services.sleeper_fantasy_service import SleeperFantasyService

                sleeper_service_temp = SleeperFantasyService()
                league_details = await sleeper_service_temp.get_league_details(
                    current_league_id
                )
                roster_positions = league_details.get("roster_positions", [])
                starting_positions = [
                    pos for pos in roster_positions if pos not in ["BN", "IR"]
                ]

                # Count required starting positions
                position_requirements = {}
                for pos in starting_positions:
                    position_requirements[pos] = position_requirements.get(pos, 0) + 1

                logger.info(f"League roster requirements: {position_requirements}")

                # Analyze each player on the roster - first pass: calculate projections
                logger.info(f"Processing {len(team_roster)} players on roster")
                player_projections = []

                for i, player in enumerate(team_roster[:15]):  # Limit to 15 players
                    try:
                        sleeper_player_id = player.get("player_id")
                        logger.info(
                            f"Processing player {i+1}: {player.get('name')} ({sleeper_player_id})"
                        )
                        if not sleeper_player_id:
                            logger.warning(f"No player_id for player: {player}")
                            continue

                        # Map Sleeper player ID to fantasy_players.id for analytics lookup
                        analytics = None
                        try:
                            # Query database for the mapping
                            fantasy_player_query = db.execute(
                                text(
                                    "SELECT id FROM fantasy_players WHERE platform_player_id = :sleeper_id"
                                ),
                                {"sleeper_id": str(sleeper_player_id)},
                            )
                            fantasy_player_row = fantasy_player_query.fetchone()

                            if fantasy_player_row:
                                fantasy_player_id = fantasy_player_row[0]
                                logger.info(
                                    f"Mapped Sleeper ID {sleeper_player_id} to fantasy_players.id {fantasy_player_id}"
                                )

                                # Now get analytics using the correct ID
                                analytics = (
                                    await analytics_service.get_player_analytics(
                                        fantasy_player_id, season=2024
                                    )
                                )
                                logger.info(
                                    f"Analytics result for {player.get('name')}: {len(analytics) if analytics else 0} records"
                                )
                            else:
                                logger.warning(
                                    f"No fantasy_players mapping found for Sleeper ID {sleeper_player_id}"
                                )
                        except Exception as e:
                            logger.warning(
                                f"Error mapping/fetching analytics for player {sleeper_player_id}: {e}"
                            )
                            analytics = None

                        # Calculate projected points based on recent performance
                        projected_points = 0.0
                        confidence = 75  # Base confidence

                        if analytics and len(analytics) > 0:
                            # Use average of last 3 games
                            recent_games = analytics[:3]
                            game_points = [
                                game.get("ppr_points", 0) for game in recent_games
                            ]
                            total_points = sum(game_points)
                            projected_points = (
                                total_points / len(recent_games)
                                if recent_games
                                else 0.0
                            )

                            # Calculate confidence based on data quality and consistency
                            position = player.get("position", "")
                            confidence = calculate_confidence(
                                game_points, len(analytics), position
                            )
                            logger.info(
                                f"Player {player.get('name')} analytics: {len(analytics)} games, projected: {projected_points:.1f}, confidence: {confidence}%"
                            )
                        else:
                            # Fallback projection based on position
                            position_projections = {
                                "QB": 24.5,
                                "RB": 15.2,
                                "WR": 13.8,
                                "TE": 9.5,
                                "K": 8.2,
                                "DEF": 7.8,
                            }
                            projected_points = position_projections.get(
                                player.get("position", ""), 8.0
                            )
                            confidence = 50  # Lower confidence for projections without recent data
                            logger.info(
                                f"Player {player.get('name')} using fallback projection: {projected_points}, confidence: {confidence}%"
                            )

                        # Store player projection data for later START/SIT assignment
                        position = player.get("position", "BENCH")

                        # Check injury status
                        injury_status = player.get("injury_status")
                        status = player.get("status")
                        is_injured = injury_status in [
                            "Out",
                            "IR",
                            "PUP",
                            "Suspended",
                        ] or status in ["Inactive", "Injured Reserve"]

                        # Adjust confidence and reason if injured
                        if is_injured:
                            confidence = 10  # Very low confidence for injured players
                            injury_reason = f" (INJURED: {injury_status or status})"
                        else:
                            injury_reason = ""

                        player_data = {
                            "player_id": sleeper_player_id,
                            "player_name": player.get("name", "Unknown Player"),
                            "name": player.get("name", "Unknown Player"),
                            "position": position,
                            "team": player.get("team", "N/A"),
                            "confidence": confidence,
                            "projected_points": round(projected_points, 1),
                            "has_analytics": analytics is not None
                            and len(analytics) > 0,
                            "injury_status": injury_status,
                            "status": status,
                            "is_injured": is_injured,
                            "reason": (
                                f"Based on recent performance averaging {projected_points:.1f} pts{injury_reason}"
                                if analytics
                                else f"Projected {projected_points:.1f} pts (no recent data){injury_reason}"
                            ),
                            "league_name": league.get("name", "Unknown League"),
                            "league_context": {
                                "league_id": current_league_id,
                                "league_name": league.get("name", "Unknown League"),
                                "team_name": user_team.get("name", "Your Team"),
                            },
                        }
                        player_projections.append(player_data)
                        logger.info(
                            f"Added projection for {player.get('name')}: {projected_points:.1f} pts, injury_status: {injury_status}, status: {status}, is_injured: {is_injured}"
                        )

                    except Exception as player_error:
                        logger.warning(
                            f"Failed to analyze player {player.get('player_id')}: {player_error}"
                        )
                        continue

                # Second pass: Assign START/SIT based on projected points and roster requirements
                logger.info(
                    f"Assigning START/SIT for {len(player_projections)} players"
                )

                # Sort players by position and projected points (highest first)
                players_by_position = {}
                for player in player_projections:
                    pos = player["position"]
                    if pos not in players_by_position:
                        players_by_position[pos] = []
                    players_by_position[pos].append(player)

                # Sort each position by health first, then projected points (descending)
                for pos in players_by_position:
                    players_by_position[pos].sort(
                        key=lambda x: (x["is_injured"], -x["projected_points"])
                    )

                # Assign START/SIT based on roster requirements
                for pos, players in players_by_position.items():
                    required_starters = position_requirements.get(pos, 0)
                    logger.info(
                        f"Position {pos}: {len(players)} players, {required_starters} starters required"
                    )

                    for i, player in enumerate(players):
                        rank_in_position = i + 1
                        is_starter = rank_in_position <= required_starters

                        # Create recommendation
                        recommendation = {
                            **player,  # Include all player data
                            "recommendation": "START" if is_starter else "SIT",
                            "rank_in_position": rank_in_position,
                            "total_in_position": len(players),
                        }
                        recommendations.append(recommendation)
                        logger.info(
                            f"{player['player_name']} ({pos}): {player['projected_points']} pts, rank #{rank_in_position}, {'START' if is_starter else 'SIT'}"
                        )

                # Handle FLEX positions (RB/WR/TE can fill FLEX spots)
                flex_positions = position_requirements.get("FLEX", 0)
                if flex_positions > 0:
                    logger.info(f"Processing {flex_positions} FLEX positions")

                    # Get all RB/WR/TE players who are currently marked as SIT
                    flex_eligible = [
                        r
                        for r in recommendations
                        if r["position"] in ["RB", "WR", "TE"]
                        and r["recommendation"] == "SIT"
                    ]

                    # Sort by health first, then projected points (highest first)
                    flex_eligible.sort(
                        key=lambda x: (x["is_injured"], -x["projected_points"])
                    )

                    # Promote top FLEX-eligible players to START
                    for i in range(min(flex_positions, len(flex_eligible))):
                        flex_eligible[i]["recommendation"] = "START"
                        logger.info(
                            f"FLEX promotion: {flex_eligible[i]['player_name']} -> START"
                        )

            except Exception as league_error:
                logger.warning(
                    f"Failed to get recommendations for league {league.get('league_id')}: {league_error}"
                )
                continue

        # Sort recommendations: START players first, then by projected points
        recommendations.sort(
            key=lambda x: (x["recommendation"] != "START", -x["projected_points"])
        )

        return {
            "status": "success",
            "recommendations": recommendations,
            "message": f"Generated {len(recommendations)} start/sit recommendations for week {week} based on your roster",
        }
    except Exception as e:
        logger.error(f"Error getting start/sit recommendations for week {week}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get start/sit recommendations"
        )


@router.get("/api/fantasy/recommendations/waiver-wire/{week}")
async def get_waiver_wire_recommendations(
    week: int, current_user: dict = Depends(get_current_user)
):
    """Get waiver wire recommendations for a given week"""
    try:
        from app.services.sleeper_fantasy_service import SleeperFantasyService

        sleeper_service = SleeperFantasyService()

        # Get trending players being added
        trending_adds = await sleeper_service.get_trending_players("add")

        # Get trending players being dropped for additional context
        trending_drops = await sleeper_service.get_trending_players("drop")

        # Format recommendations with both adds and drops
        recommendations = []

        # Add top trending additions
        for player in trending_adds[:10]:  # Top 10 trending adds
            trend_count = player.get("trend_count", 0)
            # Calculate priority score based on trend count (normalize to 0-10 scale)
            priority_score = min(10.0, max(1.0, trend_count / 10000))
            is_high_priority = trend_count > 50000
            faab_percentage = min(20, max(3, int(trend_count / 10000)))

            recommendations.append(
                {
                    **player,
                    "recommendation_type": "add",
                    "priority": "high" if is_high_priority else "medium",
                    "priority_score": round(priority_score, 1),
                    "trend_count": trend_count,
                    "waiver_suggestion": {
                        "suggestion_type": "FAAB",
                        "faab_percentage": faab_percentage,
                        "claim_advice": (
                            f"Top waiver priority"
                            if is_high_priority
                            else "Medium priority"
                        ),
                    },
                    "suggested_fab_percentage": faab_percentage,
                }
            )

        # Add context about trending drops
        for player in trending_drops[:5]:  # Top 5 trending drops
            recommendations.append(
                {
                    **player,
                    "recommendation_type": "drop",
                    "priority": "low",
                    "priority_score": 1.0,
                    "trend_count": player.get("trend_count", 0),
                    "waiver_suggestion": {
                        "suggestion_type": "DROP",
                        "claim_advice": "Consider dropping",
                    },
                    "suggested_fab_percentage": 0,
                }
            )

        return {
            "status": "success",
            "recommendations": recommendations,
            "message": f"Retrieved {len(recommendations)} waiver wire recommendations for week {week}",
        }
    except Exception as e:
        logger.error(f"Error getting waiver wire recommendations for week {week}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get waiver wire recommendations"
        )
