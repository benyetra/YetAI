"""WNBA game totals (O/U) projections — port of NBA totals_projector with WNBA constants."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAGameLines,
    WNBAPlayerInjuryStatus,
    WNBARecentGames,
    WNBATeamDefenseStats,
    WNBATeamOffenseStats,
    WNBATeamRoster,
    WNBATotalsProjections,
)
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba.totals_ml import enrich_projection

logger = logging.getLogger(__name__)

db = None

LEAGUE_AVG_PACE = 80.0
LEAGUE_AVG_ORTG = 102.0
LEAGUE_AVG_DRTG = 102.0
LEAGUE_AVG_TOTAL = 164.0
DENVER_ALTITUDE_BONUS = 0.0  # WNBA has no altitude venues

# Fallback when a named star has thin recent history (expansion / early season).
STAR_PLAYER_IMPACTS = {
    "a'ja wilson": 4.8,
    "caitlin clark": 4.8,
    "breanna stewart": 4.5,
    "napheesa collier": 4.2,
    "sabrina ionescu": 4.2,
    "alyssa thomas": 4.0,
    "kelsey plum": 3.8,
    "jewell loyd": 3.8,
    "jonquel jones": 3.8,
    "arike ogunbowale": 3.8,
    "jackie young": 3.5,
    "chelsea gray": 3.5,
    "satou sabally": 3.5,
    "rhyne howard": 3.3,
    "skylar diggins-smith": 3.3,
    "kelsey mitchell": 3.3,
    "angel reese": 3.3,
    "paige bueckers": 3.5,
}

# Usage-weighted injury impact (primary path).
INJURY_LOOKBACK_GAMES = 10
INJURY_MIN_GAMES = 5
INJURY_ROTATION_MINUTES = 18.0
INJURY_MAX_PLAYER_IMPACT = 6.0
INJURY_MAX_TEAM_IMPACT = 12.0
INJURY_DEFAULT_REPLACEABILITY = 0.55  # when usage% missing

TEAM_NAME_TO_ID: dict[str, int] = {}
TEAM_ID_TO_NAME: dict[int, str] = {}


def load_team_data() -> None:
    """Build team name/id maps from pred_team_offense_stats / pred_team_defense_stats."""
    global TEAM_NAME_TO_ID, TEAM_ID_TO_NAME
    if TEAM_NAME_TO_ID:
        return
    for model in (WNBATeamOffenseStats, WNBATeamDefenseStats):
        rows = db.query(model.team_id, model.team_name).distinct(model.team_id).all()
        for team_id, team_name in rows:
            if team_id is None or not team_name:
                continue
            TEAM_NAME_TO_ID[team_name.lower()] = int(team_id)
            TEAM_ID_TO_NAME[int(team_id)] = team_name
    # Phase 1: no TodayActivePlayers fallback (Phase 2 only)


def get_team_id_from_name(team_name: str) -> Optional[int]:
    """Get team ID from team name."""
    load_team_data()
    return TEAM_NAME_TO_ID.get(team_name.lower())


def get_team_name_from_id(team_id: int) -> Optional[str]:
    """Get team name from team ID."""
    load_team_data()
    return TEAM_ID_TO_NAME.get(team_id)


def estimate_game_pace(team_a_pace: float, team_b_pace: float) -> float:
    """
    Estimate total possessions for the game.
    Teams typically meet somewhere between their paces,
    weighted toward the slower team slightly.
    Regress 15% toward league mean.
    """
    if not team_a_pace or not team_b_pace:
        return LEAGUE_AVG_PACE

    raw_pace = (team_a_pace + team_b_pace) / 2

    # Regression to league mean (15% weight)
    adjusted_pace = (raw_pace * 0.85) + (LEAGUE_AVG_PACE * 0.15)

    return adjusted_pace


def matchup_efficiency(team_ortg: float, opp_drtg: float) -> float:
    """
    Adjust offensive rating based on opponent's defense.
    If opponent defense is better than average, reduce expected points.
    """
    if not team_ortg:
        team_ortg = LEAGUE_AVG_ORTG
    if not opp_drtg:
        opp_drtg = LEAGUE_AVG_DRTG

    defensive_factor = opp_drtg / LEAGUE_AVG_DRTG
    adjusted_ortg = team_ortg * defensive_factor

    return adjusted_ortg


def project_team_score(adjusted_ortg: float, game_pace: float) -> float:
    """
    Convert efficiency and pace to projected points.
    """
    projected_points = (adjusted_ortg / 100) * game_pace
    return projected_points


def get_team_pace_and_efficiency(team_name: str) -> Dict:
    """
    Get pace and efficiency metrics for a team from database.
    Uses WNBATeamOffenseStats and WNBATeamDefenseStats tables.
    """
    team_id = get_team_id_from_name(team_name)

    result = {
        "pace": LEAGUE_AVG_PACE,
        "offensive_rating": LEAGUE_AVG_ORTG,
        "defensive_rating": LEAGUE_AVG_DRTG,
        "points_per_game": LEAGUE_AVG_TOTAL / 2,
        "points_allowed_per_game": LEAGUE_AVG_TOTAL / 2,
    }

    if not team_id:
        logger.warning(f"Team ID not found for: {team_name}")
        return result

    # Get offense stats
    offense = db.query(WNBATeamOffenseStats).filter_by(team_id=team_id).first()
    if offense:
        result["pace"] = offense.pace or result["pace"]
        result["points_per_game"] = offense.points_per_game or result["points_per_game"]

    # Get defense stats
    defense = db.query(WNBATeamDefenseStats).filter_by(team_id=team_id).first()
    if defense:
        result["defensive_rating"] = (
            defense.defensive_rating or result["defensive_rating"]
        )
        result["points_allowed_per_game"] = (
            defense.points_allowed_per_game or result["points_allowed_per_game"]
        )
        # If pace not in offense, check defense
        if not offense or not offense.pace:
            result["pace"] = defense.pace or result["pace"]

    # Calculate offensive rating if not directly available
    # ORtg = (PPG / Pace) * 100
    if offense and offense.points_per_game and result["pace"]:
        result["offensive_rating"] = (offense.points_per_game / result["pace"]) * 100

    return result


def get_projected_starters(team_name: str, num_starters: int = 5) -> List[Dict]:
    """
    Get projected starting lineup for a team based on recent minutes played.
    Excludes players who are OUT or on IR.

    Returns list of player dicts with name, position, avg_minutes, and status.
    """
    team_id = get_team_id_from_name(team_name)
    if not team_id:
        return []

    # Get roster
    roster = db.query(WNBATeamRoster).filter_by(team_id=team_id).all()
    if not roster:
        return []

    player_stats = []

    for player in roster:
        # Get injury status
        injury = (
            db.query(WNBAPlayerInjuryStatus)
            .filter_by(player_id=player.player_id)
            .first()
        )
        status = injury.status.upper() if injury and injury.status else "ACTIVE"

        # Skip players who are definitely out
        if status in ("OUT", "IR"):
            continue

        # Get recent games to calculate average minutes
        recent_games = (
            db.query(WNBARecentGames)
            .filter_by(player_id=player.player_id)
            .order_by(WNBARecentGames.game_date.desc())
            .limit(10)
            .all()
        )

        if recent_games:
            avg_minutes = sum(g.minutes or 0 for g in recent_games) / len(recent_games)
            avg_points = sum(g.points or 0 for g in recent_games) / len(recent_games)
        else:
            avg_minutes = 0
            avg_points = 0

        # Only include players with meaningful minutes
        if avg_minutes >= 15:
            player_stats.append(
                {
                    "name": player.player_name,
                    "position": player.position or "N/A",
                    "avg_minutes": round(avg_minutes, 1),
                    "avg_points": round(avg_points, 1),
                    "status": status if status != "ACTIVE" else None,
                }
            )

    # Sort by average minutes (most minutes = likely starter)
    player_stats.sort(key=lambda x: x["avg_minutes"], reverse=True)

    # Return top N as projected starters
    return player_stats[:num_starters]


def estimate_player_totals_impact_from_games(games: list) -> float | None:
    """
    Usage-weighted points impact when a rotation player is unavailable.

    Higher usage ⇒ less replaceable ⇒ larger impact. Returns None for thin
    history or bench minutes so callers can fall back to STAR_PLAYER_IMPACTS.
    """
    playable = [
        g
        for g in games
        if getattr(g, "minutes", None) not in (None, 0)
        and getattr(g, "points", None) is not None
    ]
    if len(playable) < INJURY_MIN_GAMES:
        return None
    sample = playable[:INJURY_LOOKBACK_GAMES]
    avg_min = sum(float(g.minutes) for g in sample) / len(sample)
    if avg_min < INJURY_ROTATION_MINUTES:
        return None
    avg_pts = sum(float(g.points) for g in sample) / len(sample)
    usages = [
        float(g.usage_percentage)
        for g in sample
        if getattr(g, "usage_percentage", None) is not None
    ]
    if usages:
        avg_usg = sum(usages) / len(usages)
        # usage 15% → ~0.62 replaceable; usage 35% → ~0.42 replaceable
        replaceability = max(0.35, min(0.70, 0.75 - (avg_usg / 100.0) * 0.9))
    else:
        replaceability = INJURY_DEFAULT_REPLACEABILITY
    impact = avg_pts * (1.0 - replaceability)
    return min(float(impact), INJURY_MAX_PLAYER_IMPACT)


def _load_recent_games_for_injury(player_id: int) -> list:
    return (
        db.query(WNBARecentGames)
        .filter(
            WNBARecentGames.player_id == player_id,
            WNBARecentGames.minutes.isnot(None),
            WNBARecentGames.minutes > 0,
        )
        .order_by(WNBARecentGames.game_date.desc())
        .limit(INJURY_LOOKBACK_GAMES)
        .all()
    )


def calculate_injury_impact(
    team_name: str, game_date: date
) -> Tuple[float, List[Dict]]:
    """
    Calculate total impact on expected score from injuries.

    Primary: usage-weighted impact from recent box scores for any rotation
    player ruled out/doubtful/questionable. Fallback: STAR_PLAYER_IMPACTS when
    history is thin (early season / expansion).
    """
    team_id = get_team_id_from_name(team_name)
    if not team_id:
        return 0.0, []

    total_impact = 0.0
    injury_list: List[Dict] = []

    roster = db.query(WNBATeamRoster).filter_by(team_id=team_id).all()

    for player in roster:
        injury = (
            db.query(WNBAPlayerInjuryStatus)
            .filter_by(player_id=player.player_id)
            .first()
        )
        if not injury or injury.status not in ("out", "doubtful", "questionable", "ir"):
            continue

        if injury.status in ("out", "ir"):
            probability = 1.0
        elif injury.status == "doubtful":
            probability = 0.75
        elif injury.status == "questionable":
            probability = 0.50
        else:
            probability = 0.25

        games = _load_recent_games_for_injury(player.player_id)
        base_impact = estimate_player_totals_impact_from_games(games)
        method = "usage"
        if base_impact is None:
            player_name_lower = (player.player_name or "").lower()
            if player_name_lower not in STAR_PLAYER_IMPACTS:
                continue
            base_impact = STAR_PLAYER_IMPACTS[player_name_lower]
            method = "star_fallback"

        adjusted_impact = base_impact * probability
        total_impact += adjusted_impact
        injury_list.append(
            {
                "player": player.player_name,
                "status": injury.status.upper(),
                "impact": round(-adjusted_impact, 1),
                "method": method,
            }
        )

    total_impact = min(total_impact, INJURY_MAX_TEAM_IMPACT)
    return -total_impact, sorted(injury_list, key=lambda x: x["impact"])


def calculate_rest_adjustment(home_team: str, away_team: str, game_date: date) -> float:
    """
    Calculate adjustment based on rest days.
    Back-to-back games typically result in lower scoring.

    NOTE: Due to potentially stale game data, we use conservative adjustments.
    Research shows B2B impact is ~2-3 points per team, we use 2.0 to be safe.
    """
    adjustment = 0.0

    # Get team IDs
    home_id = get_team_id_from_name(home_team)
    away_id = get_team_id_from_name(away_team)

    for team_id, is_home in [(home_id, True), (away_id, False)]:
        if not team_id:
            continue

        # Check most recent game
        recent_game = (
            db.query(WNBARecentGames)
            .filter(WNBARecentGames.game_date < game_date)
            .join(WNBATeamRoster, WNBARecentGames.player_id == WNBATeamRoster.player_id)
            .filter(WNBATeamRoster.team_id == team_id)
            .order_by(WNBARecentGames.game_date.desc())
            .first()
        )

        if recent_game:
            days_rest = (game_date - recent_game.game_date).days

            if days_rest == 1:  # Back-to-back
                adjustment -= 2.0  # B2B reduces total by ~2 points per team
            elif days_rest == 0:  # Same day (rare but possible)
                adjustment -= 3.0
            elif days_rest >= 4:  # Well rested
                adjustment += 0.5  # Slightly higher scoring

    # Cap total rest adjustment (both teams combined shouldn't exceed ±5 points)
    adjustment = max(-5.0, min(adjustment, 2.0))

    return adjustment


def calculate_venue_adjustment(home_team: str) -> float:
    """
    Calculate adjustment for venue factors.
    WNBA: no altitude factor; kept as a hook.
    """
    adjustment = 0.0

    # Altitude bonus (WNBA: no qualifying venues; constant is 0)
    if "nuggets" in home_team.lower() or "denver" in home_team.lower():
        adjustment += DENVER_ALTITUDE_BONUS

    return adjustment


def _points_values(games) -> list[float]:
    """Extract numeric points from recent-game rows; skip null/invalid."""
    values: list[float] = []
    for game in games:
        pts = game.points
        if pts is None:
            continue
        try:
            values.append(float(pts))
        except (TypeError, ValueError):
            continue
    return values


def calculate_team_form(team_name: str, num_recent_games: int = 5) -> float:
    """
    Calculate a team's recent form by comparing tracked players' recent
    performance to their season averages.

    Returns: Points deviation (positive = hot streak, negative = cold streak)

    Methodology:
    - For each tracked player on the roster, calculate their season avg PPG
    - Compare their last N games to their season average
    - Sum the deviations to estimate team-level form
    """
    from sqlalchemy import func

    team_id = get_team_id_from_name(team_name)
    if not team_id:
        return 0.0

    # Get roster player IDs
    roster = db.query(WNBATeamRoster).filter_by(team_id=team_id).all()
    if not roster:
        return 0.0

    player_ids = [p.player_id for p in roster]

    total_deviation = 0.0
    players_counted = 0

    for player_id in player_ids:
        # Get all games for this player
        all_games = db.query(WNBARecentGames).filter_by(player_id=player_id).all()

        season_points = _points_values(all_games)
        if len(season_points) < 5:  # Need enough games with scored points
            continue

        season_avg_ppg = sum(season_points) / len(season_points)

        if season_avg_ppg < 5.0:  # Skip low-minute players
            continue

        # Get last N games
        recent_games = sorted(all_games, key=lambda x: x.game_date, reverse=True)[
            :num_recent_games
        ]
        recent_points = _points_values(recent_games)
        if not recent_points:
            continue

        recent_avg_ppg = sum(recent_points) / len(recent_points)

        # Calculate deviation from season average
        deviation = recent_avg_ppg - season_avg_ppg
        total_deviation += deviation
        players_counted += 1

    # If we tracked multiple players, the total deviation represents
    # how the team's scoring should deviate from baseline
    # Cap at ±8 points per team to prevent extreme adjustments
    total_deviation = max(-8.0, min(total_deviation, 8.0))

    return total_deviation


def calculate_team_form_as_of(
    team_name: str, as_of: date, num_recent_games: int = 5
) -> float:
    """Like ``calculate_team_form`` but only uses games strictly before ``as_of``."""
    team_id = get_team_id_from_name(team_name)
    if not team_id:
        return 0.0

    roster = db.query(WNBATeamRoster).filter_by(team_id=team_id).all()
    if not roster:
        return 0.0

    total_deviation = 0.0

    for player in roster:
        all_games = (
            db.query(WNBARecentGames)
            .filter(
                WNBARecentGames.player_id == player.player_id,
                WNBARecentGames.game_date < as_of,
            )
            .all()
        )
        season_points = _points_values(all_games)
        if len(season_points) < 5:
            continue

        season_avg_ppg = sum(season_points) / len(season_points)
        if season_avg_ppg < 5.0:
            continue

        recent_games = sorted(all_games, key=lambda x: x.game_date, reverse=True)[
            :num_recent_games
        ]
        recent_points = _points_values(recent_games)
        if not recent_points:
            continue

        recent_avg_ppg = sum(recent_points) / len(recent_points)
        total_deviation += recent_avg_ppg - season_avg_ppg

    return max(-8.0, min(total_deviation, 8.0))


def calculate_form_adjustment(home_team: str, away_team: str) -> float:
    """
    Calculate adjustment based on recent form (last 5 games).
    Teams on hot/cold streaks deviate from season averages.

    Returns combined form adjustment for both teams.
    Positive = expect higher scoring, Negative = expect lower scoring.
    """
    home_form = calculate_team_form(home_team)
    away_form = calculate_team_form(away_team)

    # Combined form adjustment (both teams contribute)
    total_form = home_form + away_form

    # Cap total form adjustment at ±10 points
    total_form = max(-10.0, min(total_form, 10.0))

    return total_form


def calculate_form_adjustment_as_of(
    home_team: str, away_team: str, game_date: date
) -> float:
    """Form adjustment using only games before ``game_date``."""
    home_form = calculate_team_form_as_of(home_team, game_date)
    away_form = calculate_team_form_as_of(away_team, game_date)
    total_form = home_form + away_form
    return max(-10.0, min(total_form, 10.0))


def generate_projection(
    home_team: str,
    away_team: str,
    game_date: date,
    market_total: Optional[float] = None,
) -> Dict:
    """
    Generate complete game total projection with all adjustments.

    Returns dict with projection details and market comparison.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"Projecting: {away_team} @ {home_team}")
    logger.info(f"{'='*60}")

    # Get team metrics
    home_stats = get_team_pace_and_efficiency(home_team)
    away_stats = get_team_pace_and_efficiency(away_team)

    logger.info(
        f"Home ({home_team}): Pace={home_stats['pace']:.1f}, ORtg={home_stats['offensive_rating']:.1f}, DRtg={home_stats['defensive_rating']:.1f}"
    )
    logger.info(
        f"Away ({away_team}): Pace={away_stats['pace']:.1f}, ORtg={away_stats['offensive_rating']:.1f}, DRtg={away_stats['defensive_rating']:.1f}"
    )

    # Step 1: Estimate game pace
    expected_pace = estimate_game_pace(home_stats["pace"], away_stats["pace"])
    logger.info(f"Expected Pace: {expected_pace:.1f}")

    # Step 2: Calculate matchup-adjusted efficiency
    home_adj_ortg = matchup_efficiency(
        home_stats["offensive_rating"], away_stats["defensive_rating"]
    )
    away_adj_ortg = matchup_efficiency(
        away_stats["offensive_rating"], home_stats["defensive_rating"]
    )

    logger.info(f"Adjusted ORtg - Home: {home_adj_ortg:.1f}, Away: {away_adj_ortg:.1f}")

    # Step 3: Project team scores
    home_projected = project_team_score(home_adj_ortg, expected_pace)
    away_projected = project_team_score(away_adj_ortg, expected_pace)

    base_projection = home_projected + away_projected
    logger.info(
        f"Base Projection: {base_projection:.1f} (Home: {home_projected:.1f}, Away: {away_projected:.1f})"
    )

    # Step 4: Apply adjustments
    injury_adj_home, home_injuries = calculate_injury_impact(home_team, game_date)
    injury_adj_away, away_injuries = calculate_injury_impact(away_team, game_date)
    injury_adjustment = injury_adj_home + injury_adj_away

    rest_adjustment = calculate_rest_adjustment(home_team, away_team, game_date)
    venue_adjustment = calculate_venue_adjustment(home_team)
    form_adjustment = calculate_form_adjustment(home_team, away_team)

    total_adjustment = (
        injury_adjustment + rest_adjustment + venue_adjustment + (form_adjustment * 0.3)
    )

    # Cap total adjustment to prevent extreme outliers (max ±12 points combined)
    # Even with multiple factors, adjustments beyond this are likely data errors
    total_adjustment = max(-12.0, min(total_adjustment, 12.0))

    logger.info(f"Adjustments:")
    logger.info(f"  Injuries: {injury_adjustment:+.1f}")
    logger.info(f"  Rest/Schedule: {rest_adjustment:+.1f}")
    logger.info(f"  Venue: {venue_adjustment:+.1f}")
    logger.info(f"  Form: {form_adjustment * 0.3:+.1f} (weighted)")
    logger.info(f"  Total Adjustment: {total_adjustment:+.1f}")

    # Final projection
    projected_total = base_projection + total_adjustment
    logger.info(f"PROJECTED TOTAL: {projected_total:.1f}")

    # Market comparison
    edge = None
    recommendation = "NO_PLAY"
    confidence = 0.5

    if market_total:
        edge = projected_total - market_total
        logger.info(f"Market Total: {market_total}")
        logger.info(f"Edge: {edge:+.1f}")

        if edge > 2:
            recommendation = "OVER"
            confidence = min(0.5 + (abs(edge) * 0.05), 0.85)
        elif edge < -2:
            recommendation = "UNDER"
            confidence = min(0.5 + (abs(edge) * 0.05), 0.85)
        else:
            recommendation = "NO_PLAY"
            confidence = 0.5

        logger.info(f"Recommendation: {recommendation} (Confidence: {confidence:.0%})")

    # Combine injury reports
    injury_report = {}
    if home_injuries:
        injury_report[home_team] = home_injuries
    if away_injuries:
        injury_report[away_team] = away_injuries

    # Build factors summary
    factors = {
        "pace_matchup": f"Expected {expected_pace:.1f} possessions",
        "defensive_matchup": f"Home DRtg: {home_stats['defensive_rating']:.1f}, Away DRtg: {away_stats['defensive_rating']:.1f}",
        "key_absence": None,
        "situational": None,
    }

    # Note key absences
    all_injuries = home_injuries + away_injuries
    if all_injuries:
        worst_injury = min(all_injuries, key=lambda x: x["impact"])
        factors["key_absence"] = (
            f"{worst_injury['player']} {worst_injury['status']} ({worst_injury['impact']:+.1f} pts)"
        )

    # Note situational factors
    situational_notes = []
    if rest_adjustment < -2:
        situational_notes.append("Back-to-back fatigue")
    if venue_adjustment > 0:
        pass  # no altitude factor in WNBA
    if situational_notes:
        factors["situational"] = ", ".join(situational_notes)

    # Get projected starting lineups
    home_starters = get_projected_starters(home_team)
    away_starters = get_projected_starters(away_team)

    return {
        "game_date": game_date,
        "home_team": home_team,
        "away_team": away_team,
        "projected_total": round(projected_total, 1),
        "home_projected_score": round(home_projected + (total_adjustment / 2), 1),
        "away_projected_score": round(away_projected + (total_adjustment / 2), 1),
        "base_projection": round(base_projection, 1),
        "expected_pace": round(expected_pace, 1),
        "home_offensive_rating": round(home_stats["offensive_rating"], 1),
        "away_offensive_rating": round(away_stats["offensive_rating"], 1),
        "home_defensive_rating": round(home_stats["defensive_rating"], 1),
        "away_defensive_rating": round(away_stats["defensive_rating"], 1),
        "injury_adjustment": round(injury_adjustment, 1),
        "rest_adjustment": round(rest_adjustment, 1),
        "venue_adjustment": round(venue_adjustment, 1),
        "form_adjustment": round(form_adjustment * 0.3, 1),
        "total_adjustment": round(total_adjustment, 1),
        "market_total": market_total,
        "edge": round(edge, 1) if edge else None,
        "recommendation": recommendation,
        "confidence_score": round(confidence, 2),
        "injury_report": injury_report,
        "factors": factors,
        "home_starters": home_starters,
        "away_starters": away_starters,
    }


def save_projection(projection: Dict):
    """Save projection to database."""
    try:
        # Check for existing projection
        existing = (
            db.query(WNBATotalsProjections)
            .filter_by(
                game_date=projection["game_date"],
                home_team_name=projection["home_team"],
                away_team_name=projection["away_team"],
            )
            .first()
        )

        if existing:
            # Update existing
            existing.projected_total = projection["projected_total"]
            existing.home_projected_score = projection["home_projected_score"]
            existing.away_projected_score = projection["away_projected_score"]
            existing.base_projection = projection["base_projection"]
            existing.expected_pace = projection["expected_pace"]
            existing.home_offensive_rating = projection["home_offensive_rating"]
            existing.away_offensive_rating = projection["away_offensive_rating"]
            existing.home_defensive_rating = projection["home_defensive_rating"]
            existing.away_defensive_rating = projection["away_defensive_rating"]
            existing.injury_adjustment = projection["injury_adjustment"]
            existing.rest_adjustment = projection["rest_adjustment"]
            existing.venue_adjustment = projection["venue_adjustment"]
            existing.form_adjustment = projection["form_adjustment"]
            existing.total_adjustment = projection["total_adjustment"]
            existing.market_total = projection["market_total"]
            existing.edge = projection["edge"]
            existing.recommendation = projection["recommendation"]
            existing.confidence_score = projection["confidence_score"]
            existing.injury_report = projection["injury_report"]
            existing.factors = projection["factors"]
            existing.home_starters = projection.get("home_starters")
            existing.away_starters = projection.get("away_starters")
            existing.created_at = datetime.utcnow()
        else:
            # Create new
            new_proj = WNBATotalsProjections(
                game_date=projection["game_date"],
                home_team_id=get_team_id_from_name(projection["home_team"]),
                away_team_id=get_team_id_from_name(projection["away_team"]),
                home_team_name=projection["home_team"],
                away_team_name=projection["away_team"],
                projected_total=projection["projected_total"],
                home_projected_score=projection["home_projected_score"],
                away_projected_score=projection["away_projected_score"],
                base_projection=projection["base_projection"],
                expected_pace=projection["expected_pace"],
                home_offensive_rating=projection["home_offensive_rating"],
                away_offensive_rating=projection["away_offensive_rating"],
                home_defensive_rating=projection["home_defensive_rating"],
                away_defensive_rating=projection["away_defensive_rating"],
                injury_adjustment=projection["injury_adjustment"],
                rest_adjustment=projection["rest_adjustment"],
                venue_adjustment=projection["venue_adjustment"],
                form_adjustment=projection["form_adjustment"],
                total_adjustment=projection["total_adjustment"],
                market_total=projection["market_total"],
                edge=projection["edge"],
                recommendation=projection["recommendation"],
                confidence_score=projection["confidence_score"],
                injury_report=projection["injury_report"],
                factors=projection["factors"],
                home_starters=projection.get("home_starters"),
                away_starters=projection.get("away_starters"),
            )
            db.add(new_proj)

        db.commit()
        logger.info(
            f"Saved projection for {projection['away_team']} @ {projection['home_team']}"
        )

    except Exception as e:
        logger.error(f"Error saving projection: {e}")
        db.rollback()


def get_todays_games() -> List[Dict]:
    """
    Get today's games from WNBAGameLines table.
    Returns list of game dicts with team names and market totals.
    """
    today = _today()

    games = db.query(WNBAGameLines).filter_by(game_date=today).all()

    result = []
    for game in games:
        result.append(
            {
                "home_team": game.home_team_name,
                "away_team": game.away_team_name,
                "market_total": game.total,
                "spread_home": game.spread_home,
                "game_time": game.game_time,
            }
        )

    return result


def generate_nightly_report(game_date: Optional[date] = None) -> Dict:
    """
    Generate complete nightly projection report for all games.

    Returns JSON-formatted report matching PRD specification.
    """
    if game_date is None:
        game_date = _today()

    logger.info("=" * 60)
    logger.info(f"NBA TOTALS PROJECTION REPORT - {game_date}")
    logger.info("=" * 60)

    # Get games from database
    games = get_todays_games()

    if not games:
        logger.warning("No games found for today. Checking WNBAGameLines table...")
        return {
            "report_date": str(game_date),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "games": [],
            "summary": {
                "total_games": 0,
                "value_plays": 0,
                "strong_overs": 0,
                "strong_unders": 0,
            },
        }

    logger.info(f"Found {len(games)} games for {game_date}")

    projections = []
    value_plays = 0
    strong_overs = 0
    strong_unders = 0

    for game in games:
        projection = generate_projection(
            home_team=game["home_team"],
            away_team=game["away_team"],
            game_date=game_date,
            market_total=game["market_total"],
        )
        enrich_projection(projection)

        # Save to database
        save_projection(projection)

        projections.append(projection)

        # Track value plays
        if projection["edge"] and abs(projection["edge"]) >= 3:
            value_plays += 1
            if projection["edge"] > 0:
                strong_overs += 1
            else:
                strong_unders += 1

    # Build report
    report = {
        "report_date": str(game_date),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "games": projections,
        "summary": {
            "total_games": len(projections),
            "value_plays": value_plays,
            "strong_overs": strong_overs,
            "strong_unders": strong_unders,
        },
    }

    # Print summary
    print("\n" + "=" * 80)
    print(f"NBA TOTALS PROJECTIONS - {game_date}")
    print("=" * 80)
    print(f"{'Matchup':<35} {'Projected':>10} {'Market':>10} {'Edge':>8} {'Rec':>10}")
    print("-" * 80)

    for proj in projections:
        matchup = f"{proj['away_team'][:15]} @ {proj['home_team'][:15]}"
        projected = f"{proj['projected_total']:.1f}"
        market = f"{proj['market_total']}" if proj["market_total"] else "N/A"
        edge = f"{proj['edge']:+.1f}" if proj["edge"] else "N/A"
        rec = proj["recommendation"]

        print(f"{matchup:<35} {projected:>10} {market:>10} {edge:>8} {rec:>10}")

    print("=" * 80)
    print(
        f"Value Plays (3+ edge): {value_plays} | Overs: {strong_overs} | Unders: {strong_unders}"
    )
    print("=" * 80)

    return report


def _today():
    return now_eastern().date()


def run(game_date: date | None = None) -> dict:
    if game_date is None:
        game_date = _today()
    global db
    db = SessionLocal()
    try:
        report = generate_nightly_report(game_date)
        games = report.get("games") or []
        return {
            "status": "ok",
            "date": str(game_date),
            "games": len(games),
            "value_plays": report.get("summary", {}).get("value_plays", 0),
            "generated_at": report.get("generated_at"),
        }
    finally:
        db.close()
