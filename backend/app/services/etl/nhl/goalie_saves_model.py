"""
NHL Goalie Saves Prediction Model
Predicts goalie saves based on opponent shots and goalie performance
"""

import sys
import os

from app.services.etl.nhl._db import db_session
from app.models.predictions_models import (
    NHLGoalieActuals, NHLGoalie, NHLTeamStats,
    NHLGameStats, NHLGoaliePredictions
)
from datetime import datetime, date
import numpy as np
from collections import defaultdict

def calculate_goalie_recent_form(goalie_id, games_back=10, use_weighted=True):
    """
    IMPROVEMENT #1: Enhanced recent form with optimal 10-game window
    Calculate goalie's recent save percentage with exponential decay weighting
    Most recent games weighted more heavily

    Changed from 5 to 10 games based on statistical analysis showing
    10-game window provides better predictive power with historical data
    """
    recent_games = db_session.query(NHLGoalieActuals).filter_by(
        goalie_id=goalie_id
    ).order_by(
        NHLGoalieActuals.game_date.desc()
    ).limit(games_back).all()

    if not recent_games:
        return None, None

    if not use_weighted:
        # Simple average (old method)
        total_saves = sum(g.actual_saves for g in recent_games)
        total_shots = sum(g.actual_shots_against for g in recent_games)
        avg_saves = total_saves / len(recent_games)
        save_pct = total_saves / total_shots if total_shots > 0 else 0
        return save_pct, avg_saves

    # IMPROVED: Exponential decay weights optimized for 10 games
    # Steeper decay: recent games matter much more
    # [0.22, 0.18, 0.14, 0.12, 0.10, 0.08, 0.06, 0.05, 0.03, 0.02]
    weights = [0.22, 0.18, 0.14, 0.12, 0.10, 0.08, 0.06, 0.05, 0.03, 0.02][:len(recent_games)]

    # Normalize weights if we have fewer than 10 games
    if len(weights) < len(recent_games):
        weights = weights[:len(recent_games)]
    weight_sum = sum(weights)
    weights = [w / weight_sum for w in weights]

    # Calculate weighted save percentage
    weighted_saves = 0
    weighted_shots = 0
    weighted_avg_saves = 0

    for i, game in enumerate(recent_games):
        weight = weights[i]
        weighted_saves += game.actual_saves * weight
        weighted_shots += game.actual_shots_against * weight
        weighted_avg_saves += game.actual_saves * weight

    save_pct = weighted_saves / weighted_shots if weighted_shots > 0 else 0

    return save_pct, weighted_avg_saves

def get_team_defensive_rating(team_name):
    """
    Get team's defensive rating (shots against per game)
    Lower = better defense = fewer shots for opponent
    """
    team_stats = db_session.query(NHLTeamStats).filter_by(team_name=team_name).first()

    if not team_stats or team_stats.games_played == 0:
        return 30.0  # League average

    # Use recent form if available
    if team_stats.last_10_shots_against_per_game and team_stats.last_10_shots_against_per_game > 0:
        return team_stats.last_10_shots_against_per_game

    return team_stats.shots_against_per_game if team_stats.shots_against_per_game else 30.0

def get_opponent_shots_per_game(team_name, games_back=10):
    """Get opponent's average shots per game"""
    team_stats = db_session.query(NHLTeamStats).filter_by(team_name=team_name).first()

    if not team_stats or team_stats.games_played == 0:
        return 30.0  # League average default

    # Use last 10 games if available, otherwise season average
    if team_stats.last_10_shots_for_per_game and team_stats.last_10_shots_for_per_game > 0:
        return team_stats.last_10_shots_for_per_game

    return team_stats.shots_for_per_game if team_stats.shots_for_per_game else 30.0

def get_time_of_day_adjustment(game_time):
    """
    Adjust shots based on game time
    Afternoon games tend to be slower/fewer shots
    Prime time games are faster-paced

    Args:
        game_time: datetime object

    Returns:
        float: Shot adjustment multiplier
    """
    if not game_time:
        return 1.0

    # Convert to Eastern Time for consistency
    hour_et = game_time.hour  # Assuming already in ET

    # Afternoon games (12pm-5pm ET): Slower pace, -5% shots
    if 12 <= hour_et < 17:
        return 0.95

    # Prime time (7pm-8pm ET): Normal pace
    elif 19 <= hour_et < 20:
        return 1.0

    # Late games (10pm+ ET): Slightly faster, +2% shots
    elif hour_et >= 22:
        return 1.02

    # All other times: Normal
    return 1.0

def check_rest_days(goalie, game_date):
    """
    Check goalie rest days and return adjustment factor
    Returns: (days_rest, rest_category, sv_pct_adjustment, shots_adjustment)

    Rest impacts:
    - 0-1 days (B2B): Tired goalie, fewer shots typically seen
    - 2-3 days: Normal rest
    - 4-6 days: Well rested, slight performance boost
    - 7+ days: Extended rest, may be rusty initially
    """
    if not goalie.last_game_date:
        return None, 'unknown', 1.0, 1.0

    from datetime import timedelta
    days_rest = (game_date - goalie.last_game_date).days

    if days_rest == 1:
        # Back-to-back: Tired goalie, games tend to have fewer shots
        return days_rest, 'back_to_back', 0.985, 0.87  # -1.5% SV%, -13% shots
    elif days_rest in [2, 3]:
        # Normal rest: No adjustment
        return days_rest, 'normal', 1.0, 1.0
    elif days_rest in [4, 5, 6]:
        # Well rested: Slight performance boost
        return days_rest, 'well_rested', 1.015, 1.0  # +1.5% SV%, normal shots
    else:  # 7+ days
        # Extended rest: May be rusty
        return days_rest, 'extended_rest', 0.99, 1.0  # -1% SV%, normal shots

    return days_rest, 'normal', 1.0, 1.0

def get_home_away_save_pct(goalie, is_home):
    """Get goalie's home or away save percentage"""
    if is_home:
        if goalie.home_games_played and goalie.home_games_played >= 3 and goalie.home_save_pct:
            return goalie.home_save_pct
    else:
        if goalie.away_games_played and goalie.away_games_played >= 3 and goalie.away_save_pct:
            return goalie.away_save_pct

    # Fallback to overall save percentage
    return goalie.save_pct

def detect_goalie_momentum(goalie_id):
    """
    Detect if goalie is on a hot or cold streak
    Returns: (is_hot, is_cold, trend_value, sv_pct_adjustment)

    Hot streak: Last 3 games all above season average
    Cold streak: Last 3 games all below season average
    Trend: Positive if improving, negative if declining
    """
    # Get goalie's season average
    goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()
    if not goalie or not goalie.save_pct:
        return False, False, 0.0, 1.0

    season_avg = goalie.save_pct

    # Get last 3 games
    recent_games = db_session.query(NHLGoalieActuals).filter_by(
        goalie_id=goalie_id
    ).order_by(
        NHLGoalieActuals.game_date.desc()
    ).limit(3).all()

    if len(recent_games) < 3:
        return False, False, 0.0, 1.0

    # Calculate save pct for each game
    game_sv_pcts = []
    for game in recent_games:
        if game.actual_shots_against > 0:
            sv_pct = game.actual_saves / game.actual_shots_against
            game_sv_pcts.append(sv_pct)

    if len(game_sv_pcts) < 3:
        return False, False, 0.0, 1.0

    # Check for hot/cold streaks
    is_hot = all(sv_pct > season_avg for sv_pct in game_sv_pcts)
    is_cold = all(sv_pct < season_avg for sv_pct in game_sv_pcts)

    # Calculate trend (compare first game to last game in our sample)
    # Positive = improving, negative = declining
    trend = game_sv_pcts[0] - game_sv_pcts[-1]  # Most recent minus oldest

    # Calculate adjustment based on momentum
    adjustment = 1.0
    if is_hot:
        # Hot streak: +2.5% boost
        adjustment = 1.025
    elif is_cold:
        # Cold streak: -2.5% penalty
        adjustment = 0.975
    elif abs(trend) > 0.015:  # Significant trend (>1.5% change)
        # Apply smaller adjustment based on trend direction
        if trend > 0:
            adjustment = 1.015  # Improving: +1.5%
        else:
            adjustment = 0.985  # Declining: -1.5%

    return is_hot, is_cold, trend, adjustment

def get_opponent_offensive_strength(team_name):
    """
    Get opponent's offensive strength considering:
    1. Goals per game (primary indicator of scoring ability)
    2. Shooting percentage (efficiency)
    3. Shots per game (volume)

    Returns: (goals_per_game, shooting_pct, expected_goals_impact)
    """
    team_stats = db_session.query(NHLTeamStats).filter_by(team_name=team_name).first()

    if not team_stats or team_stats.games_played == 0:
        return 3.0, 0.10, 1.0  # League averages

    # Use recent form (L10) if available
    goals_pg = team_stats.last_10_goals_for_per_game if team_stats.last_10_goals_for_per_game else team_stats.goals_for_per_game
    shooting_pct = team_stats.last_10_shooting_pct if team_stats.last_10_shooting_pct else team_stats.shooting_pct

    # Fallback to league averages if missing
    if not goals_pg:
        goals_pg = 3.0
    if not shooting_pct:
        shooting_pct = 0.10

    # Calculate expected goals impact
    # High-scoring teams (>3.5 GPG) make it harder on goalies
    # Low-scoring teams (<2.5 GPG) make it easier
    league_avg_goals = 3.0

    if goals_pg > 3.5:
        # Elite offense: saves may be harder (better shot quality)
        expected_goals_impact = 0.97  # -3% to save pct
    elif goals_pg < 2.5:
        # Weak offense: saves may be easier
        expected_goals_impact = 1.03  # +3% to save pct
    else:
        # Average offense
        expected_goals_impact = 1.0

    # Factor in shooting percentage
    # High shooting % (>11%) = dangerous team, lower SV%
    # Low shooting % (<9%) = less dangerous, higher SV%
    if shooting_pct > 0.11:
        expected_goals_impact *= 0.98  # Additional -2%
    elif shooting_pct < 0.09:
        expected_goals_impact *= 1.02  # Additional +2%

    # Expected goals (shot quality metric)
    xgf_per_game = None
    if team_stats.expected_goals_for and team_stats.games_played > 0:
        xgf_per_game = team_stats.expected_goals_for / team_stats.games_played
    else:
        xgf_per_game = 3.0

    # Factor in expected goals (shot quality)
    # If xGF significantly exceeds actual goals, team is due for positive regression
    # If actual goals exceed xGF, team is shooting hot (not sustainable)
    if xgf_per_game and goals_pg:
        xg_diff = goals_pg - xgf_per_game
        if xg_diff > 0.3:  # Overperforming xG by >0.3 GPG
            # Team shooting hot, likely to regress = easier for goalie
            expected_goals_impact *= 1.02  # +2%
        elif xg_diff < -0.3:  # Underperforming xG by >0.3 GPG
            # Team unlucky, likely to score more = harder for goalie
            expected_goals_impact *= 0.98  # -2%

    return goals_pg, shooting_pct, expected_goals_impact, xgf_per_game

def get_venue_adjustment(goalie_id, venue_name):
    """
    Calculate goalie's performance adjustment for specific venue
    Returns: (venue_adjustment, games_at_venue, avg_sv_pct_at_venue)

    Tracks performance at each specific arena, not just home/away
    """
    if not venue_name:
        return 1.0, 0, None

    # Get goalie's season average
    goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()
    if not goalie or not goalie.save_pct:
        return 1.0, 0, None

    season_avg = goalie.save_pct

    # Get all games at this venue for this goalie
    venue_games = db_session.query(NHLGoalieActuals).filter(
        db.and_(
            NHLGoalieActuals.goalie_id == goalie_id,
            NHLGoalieActuals.venue_name == venue_name
        )
    ).all()

    if len(venue_games) < 2:  # Need at least 2 games for meaningful adjustment
        return 1.0, len(venue_games), None

    # Calculate average save pct at this venue
    total_saves = sum(g.actual_saves for g in venue_games)
    total_shots = sum(g.actual_shots_against for g in venue_games)

    if total_shots == 0:
        return 1.0, len(venue_games), None

    venue_sv_pct = total_saves / total_shots

    # Calculate adjustment factor
    # If goalie performs better here, boost prediction
    # If goalie struggles here, reduce prediction
    pct_diff = venue_sv_pct - season_avg

    # Convert to adjustment (max ±3%)
    adjustment = 1.0 + min(0.03, max(-0.03, pct_diff * 0.5))

    return adjustment, len(venue_games), venue_sv_pct

def get_team_familiarity_adjustment(goalie_id, opponent_team_name):
    """
    Calculate goalie's performance vs. specific opponent
    Returns: (familiarity_adjustment, games_vs_team, avg_sv_pct_vs_team, recent_trend)

    Division rivals face each other 4-5x per season
    Performance patterns emerge with familiarity
    """
    # Get goalie's season average
    goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()
    if not goalie or not goalie.save_pct:
        return 1.0, 0, None, None

    season_avg = goalie.save_pct

    # Get all games vs. this opponent
    opponent_games = db_session.query(NHLGoalieActuals).filter(
        db.and_(
            NHLGoalieActuals.goalie_id == goalie_id,
            NHLGoalieActuals.opponent_team_name.ilike(f"%{opponent_team_name}%")
        )
    ).order_by(NHLGoalieActuals.game_date.desc()).all()

    if len(opponent_games) < 2:  # Need at least 2 games
        return 1.0, len(opponent_games), None, None

    # Calculate overall save pct vs. this team
    total_saves = sum(g.actual_saves for g in opponent_games)
    total_shots = sum(g.actual_shots_against for g in opponent_games)

    if total_shots == 0:
        return 1.0, len(opponent_games), None, None

    vs_team_sv_pct = total_saves / total_shots

    # Check recent trend (last 2 games vs. this team)
    recent_games = opponent_games[:2]
    recent_trend = None

    if len(recent_games) == 2:
        recent_saves = sum(g.actual_saves for g in recent_games)
        recent_shots = sum(g.actual_shots_against for g in recent_games)
        if recent_shots > 0:
            recent_sv_pct = recent_saves / recent_shots
            # Compare recent to overall vs. team
            trend_diff = recent_sv_pct - vs_team_sv_pct
            if trend_diff > 0.02:
                recent_trend = "improving"
            elif trend_diff < -0.02:
                recent_trend = "declining"

    # Calculate adjustment factor
    pct_diff = vs_team_sv_pct - season_avg

    # Convert to adjustment (max ±4% for familiarity)
    adjustment = 1.0 + min(0.04, max(-0.04, pct_diff * 0.6))

    # Apply additional boost/penalty for recent trend
    if recent_trend == "improving":
        adjustment *= 1.015  # +1.5%
    elif recent_trend == "declining":
        adjustment *= 0.985  # -1.5%

    return adjustment, len(opponent_games), vs_team_sv_pct, recent_trend

def calculate_workload_fatigue(goalie_id, game_date):
    """
    Calculate goalie's recent workload and fatigue level
    Returns: (games_7d, games_14d, shots_7d, is_overworked, fatigue_adjustment)

    Heavy workload = 4+ games in 7 days OR 200+ shots in 7 days
    """
    from datetime import timedelta

    seven_days_ago = game_date - timedelta(days=7)
    fourteen_days_ago = game_date - timedelta(days=14)

    # Get games in last 7 days
    recent_games_7d = db_session.query(NHLGoalieActuals).filter(
        db.and_(
            NHLGoalieActuals.goalie_id == goalie_id,
            NHLGoalieActuals.game_date >= seven_days_ago,
            NHLGoalieActuals.game_date < game_date
        )
    ).all()

    # Get games in last 14 days
    recent_games_14d = db_session.query(NHLGoalieActuals).filter(
        db.and_(
            NHLGoalieActuals.goalie_id == goalie_id,
            NHLGoalieActuals.game_date >= fourteen_days_ago,
            NHLGoalieActuals.game_date < game_date
        )
    ).all()

    games_7d = len(recent_games_7d)
    games_14d = len(recent_games_14d)
    shots_7d = sum(g.actual_shots_against for g in recent_games_7d)

    # Determine if overworked
    is_overworked = (games_7d >= 4) or (shots_7d >= 200)

    # Calculate fatigue adjustment
    fatigue_adjustment = 1.0

    if is_overworked:
        # Heavy workload: -2.5% SV%
        fatigue_adjustment = 0.975
    elif games_7d >= 3:
        # Moderate workload: -1% SV%
        fatigue_adjustment = 0.99
    elif games_7d == 0:
        # No games in 7 days: may be rusty, -0.5% SV%
        fatigue_adjustment = 0.995

    return games_7d, games_14d, shots_7d, is_overworked, fatigue_adjustment

def check_injury_status(goalie_id):
    """
    Check goalie's injury status and return adjustment
    Returns: (injury_status, games_since_injury, injury_adjustment)

    Injury impacts:
    - 'day-to-day' or 'out': Don't make predictions
    - First game back from injury: -3% SV%
    - 2-3 games back: -2% SV%
    - 4+ games back: Normal
    """
    goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()

    if not goalie:
        return 'unknown', None, 1.0

    injury_status = goalie.injury_status or 'healthy'
    games_since = goalie.games_since_injury

    # Don't predict if goalie is injured
    if injury_status in ['out', 'ir']:
        return injury_status, games_since, None  # Signal to skip prediction

    # Adjust for recent return from injury
    injury_adjustment = 1.0

    if games_since is not None:
        if games_since == 0:
            # First game back: -3% SV%
            injury_adjustment = 0.97
        elif games_since in [1, 2]:
            # 2-3 games back: -2% SV%
            injury_adjustment = 0.98
        # 3+ games back: normal

    # Day-to-day status: -1.5% SV%
    if injury_status == 'day-to-day':
        injury_adjustment *= 0.985

    return injury_status, games_since, injury_adjustment

def get_opponent_quality_rating(team_name):
    """
    Get opponent's overall strength rating (0-100)
    Used for weighting recent form by opponent quality

    Returns: (offensive_rating, defensive_rating, overall_strength)
    """
    team_stats = db_session.query(NHLTeamStats).filter_by(team_name=team_name).first()

    if not team_stats:
        return 50.0, 50.0, 50.0  # Average team

    # Calculate ratings if not already stored
    offensive_rating = team_stats.offensive_rating
    defensive_rating = team_stats.defensive_rating
    overall_strength = team_stats.overall_strength

    # If ratings not calculated, estimate based on goals/shots
    if offensive_rating is None and team_stats.games_played > 0:
        # Simple rating: goals per game normalized to 0-100
        # League avg ~3.0 GPG, elite ~3.8+, weak ~2.2-
        gpg = team_stats.goals_for_per_game or 3.0
        offensive_rating = min(100, max(0, (gpg - 2.0) * 50))

    if defensive_rating is None and team_stats.games_played > 0:
        # Inverse for defense: fewer goals against = better
        ga_pg = team_stats.goals_against_per_game or 3.0
        defensive_rating = min(100, max(0, (4.0 - ga_pg) * 50))

    if overall_strength is None:
        # Average of offense and defense
        overall_strength = (offensive_rating + defensive_rating) / 2 if offensive_rating and defensive_rating else 50.0

    return offensive_rating or 50.0, defensive_rating or 50.0, overall_strength or 50.0

def calculate_quality_weighted_recent_form(goalie_id, games_back=5):
    """
    Calculate recent form weighted by opponent quality
    Better performance vs. elite teams = higher confidence
    Stats padding vs. weak teams = discounted

    Returns: (quality_weighted_sv_pct, avg_opponent_strength)
    """
    recent_games = db_session.query(NHLGoalieActuals).filter_by(
        goalie_id=goalie_id
    ).order_by(
        NHLGoalieActuals.game_date.desc()
    ).limit(games_back).all()

    if not recent_games:
        return None, None

    total_weighted_saves = 0
    total_weighted_shots = 0
    total_opponent_strength = 0

    for game in recent_games:
        # Get opponent strength
        _, _, opp_strength = get_opponent_quality_rating(game.opponent_team_name)

        # Weight factor based on opponent strength (0.7 - 1.3)
        # Elite teams (80+ rating): 1.3x weight
        # Average teams (40-60): 1.0x weight
        # Weak teams (<30 rating): 0.7x weight
        if opp_strength >= 70:
            weight = 1.3
        elif opp_strength >= 55:
            weight = 1.1
        elif opp_strength <= 30:
            weight = 0.7
        elif opp_strength <= 45:
            weight = 0.9
        else:
            weight = 1.0

        total_weighted_saves += game.actual_saves * weight
        total_weighted_shots += game.actual_shots_against * weight
        total_opponent_strength += opp_strength

    if total_weighted_shots == 0:
        return None, None

    quality_weighted_sv_pct = total_weighted_saves / total_weighted_shots
    avg_opponent_strength = total_opponent_strength / len(recent_games)

    return quality_weighted_sv_pct, avg_opponent_strength

def get_special_teams_adjustment(opponent_team_name):
    """
    Calculate special teams impact on predicted saves
    Teams with strong power plays generate more shots and higher-quality chances
    Returns: (pp_pct, pp_adjustment, opponent_pp_opps_per_game)

    Impact:
    - Elite PP (>25%): +2% shots (more sustained pressure)
    - Good PP (20-25%): +1% shots
    - Weak PP (<15%): -1% shots (fewer quality chances)
    """
    opponent = db_session.query(NHLTeamStats).filter_by(team_name=opponent_team_name).first()

    if not opponent:
        return None, 1.0, None

    pp_pct = opponent.power_play_pct or 0.20  # Default ~20%
    pp_opps_per_game = opponent.pp_opportunities_per_game or 3.0

    # Calculate adjustment based on PP quality
    if pp_pct >= 0.25:  # Elite PP (top 10%)
        pp_adjustment = 1.02  # +2% shots
    elif pp_pct >= 0.20:  # Above average PP
        pp_adjustment = 1.01  # +1% shots
    elif pp_pct < 0.15:  # Weak PP (bottom 10%)
        pp_adjustment = 0.99  # -1% shots
    else:
        pp_adjustment = 1.0  # Average PP

    return pp_pct, pp_adjustment, pp_opps_per_game

def calculate_goalie_vs_team_history(goalie_id, opponent_team_name):
    """
    Analyze goalie's historical performance vs. specific team
    Some goalies consistently perform better/worse against certain teams
    Returns: (vs_team_sv_pct, games_vs_team, vs_team_adjustment)

    Impact:
    - Strong history (>+3% vs season avg): +1.5% SV%
    - Good history (+1-3% vs season avg): +1% SV%
    - Weak history (<-3% vs season avg): -2% SV%
    - Poor history (-1-3% vs season avg): -1% SV%
    """
    goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()

    if not goalie:
        return None, 0, 1.0

    # Get career stats vs this opponent from JSON field
    vs_opponent_stats = goalie.career_vs_opponent_stats or {}

    if opponent_team_name not in vs_opponent_stats:
        # Calculate from actuals if not in JSON
        vs_team_games = db_session.query(NHLGoalieActuals).filter_by(
            goalie_id=goalie_id,
            opponent_team_name=opponent_team_name
        ).all()

        if len(vs_team_games) < 3:  # Need at least 3 games
            return None, len(vs_team_games), 1.0

        total_saves = sum(g.actual_saves for g in vs_team_games)
        total_shots = sum(g.actual_shots_against for g in vs_team_games)
        vs_team_sv_pct = total_saves / total_shots if total_shots > 0 else 0

        # Store in JSON for future use
        vs_opponent_stats[opponent_team_name] = {
            'games': len(vs_team_games),
            'saves': total_saves,
            'shots': total_shots,
            'sv_pct': vs_team_sv_pct
        }
        goalie.career_vs_opponent_stats = vs_opponent_stats
        db_session.commit()
    else:
        stats = vs_opponent_stats[opponent_team_name]
        vs_team_sv_pct = stats['sv_pct']
        vs_team_games = stats['games']

    # Compare to season average
    season_sv_pct = goalie.save_pct or 0.900
    sv_pct_diff = vs_team_sv_pct - season_sv_pct

    # Calculate adjustment based on historical performance
    if sv_pct_diff >= 0.03:  # +3% or better vs this team
        vs_team_adj = 1.015  # +1.5% boost
    elif sv_pct_diff >= 0.01:  # +1-3% vs this team
        vs_team_adj = 1.01  # +1% boost
    elif sv_pct_diff <= -0.03:  # -3% or worse vs this team
        vs_team_adj = 0.98  # -2% penalty
    elif sv_pct_diff <= -0.01:  # -1-3% vs this team
        vs_team_adj = 0.99  # -1% penalty
    else:
        vs_team_adj = 1.0  # Neutral

    return vs_team_sv_pct, len(vs_team_games) if isinstance(vs_team_games, list) else vs_team_games, vs_team_adj

def calculate_shot_quality_adjustment(opponent_team_name):
    """
    Adjust predictions based on opponent's shot quality metrics
    Teams that generate high-danger chances are harder to stop
    Returns: (avg_shot_distance, high_danger_rate, shot_quality_adj)

    Impact:
    - Elite shot quality (close shots, high danger): -2% SV%
    - Good shot quality: -1% SV%
    - Poor shot quality (perimeter shots): +1% SV%
    """
    opponent = db_session.query(NHLTeamStats).filter_by(team_name=opponent_team_name).first()

    if not opponent:
        return None, None, 1.0

    avg_shot_distance = opponent.avg_shot_distance
    high_danger_chances_pg = opponent.high_danger_chances_against_per_game

    # If no shot quality data available, use neutral adjustment
    if not avg_shot_distance:
        return None, None, 1.0

    # Calculate shot quality adjustment
    # Shorter average distance = better shot quality = harder on goalie
    if avg_shot_distance < 25:  # Close shots (elite shooting team)
        shot_quality_adj = 0.98  # -2% SV%
    elif avg_shot_distance < 28:  # Above average shot quality
        shot_quality_adj = 0.99  # -1% SV%
    elif avg_shot_distance > 32:  # Perimeter team (easier shots)
        shot_quality_adj = 1.01  # +1% SV%
    else:
        shot_quality_adj = 1.0  # Average

    high_danger_rate = high_danger_chances_pg if high_danger_chances_pg else None

    return avg_shot_distance, high_danger_rate, shot_quality_adj

def calculate_defensive_quality_impact(goalie_team_name):
    """
    Account for defensive team quality in front of goalie
    Teams that block more shots and limit high-danger chances help their goalie
    Returns: (blocks_per_game, def_quality_adj)

    Impact:
    - Elite defense (lots of blocks, limit chances): +1.5% SV%
    - Good defense: +0.5% SV%
    - Poor defense (few blocks, allow chances): -1% SV%
    """
    team = db_session.query(NHLTeamStats).filter_by(team_name=goalie_team_name).first()

    if not team:
        return None, 1.0

    blocks_per_game = team.blocked_shots_per_game

    if not blocks_per_game:
        return None, 1.0

    # League average is ~15 blocked shots per game
    league_avg_blocks = 15.0

    if blocks_per_game >= 18:  # Elite shot blocking team
        def_quality_adj = 1.015  # +1.5% SV%
    elif blocks_per_game >= 16:  # Good shot blocking
        def_quality_adj = 1.005  # +0.5% SV%
    elif blocks_per_game < 13:  # Poor shot blocking
        def_quality_adj = 0.99  # -1% SV%
    else:
        def_quality_adj = 1.0  # Average

    return blocks_per_game, def_quality_adj

def analyze_season_long_trends(goalie_id, game_date):
    """
    IMPROVEMENT #2: Season-long performance trend analysis
    Analyzes if goalie is improving/declining throughout the season
    Returns: (trend_direction, monthly_performance, season_stage_adj)

    Impact:
    - Strong upward trend: +1% SV%
    - Declining trend: -1.5% SV%
    - Late-season fatigue (March/April): -0.5% SV%
    """
    from datetime import timedelta
    import calendar

    # Get current season games (Oct 1 - Apr 30)
    season_start = game_date.replace(month=10 if game_date.month >= 10 else 10, day=1)
    if game_date.month < 10:
        season_start = season_start.replace(year=game_date.year - 1)

    season_games = db_session.query(NHLGoalieActuals).filter(
        db.and_(
            NHLGoalieActuals.goalie_id == goalie_id,
            NHLGoalieActuals.game_date >= season_start,
            NHLGoalieActuals.game_date < game_date
        )
    ).order_by(NHLGoalieActuals.game_date.asc()).all()

    if len(season_games) < 10:
        return 'insufficient_data', None, 1.0

    # Split season into thirds and calculate SV% for each
    third_size = len(season_games) // 3
    first_third = season_games[:third_size]
    second_third = season_games[third_size:third_size*2]
    recent_third = season_games[third_size*2:]

    def calc_sv_pct(games):
        total_saves = sum(g.actual_saves for g in games)
        total_shots = sum(g.actual_shots_against for g in games)
        return total_saves / total_shots if total_shots > 0 else 0

    first_sv = calc_sv_pct(first_third) if first_third else 0
    second_sv = calc_sv_pct(second_third) if second_third else 0
    recent_sv = calc_sv_pct(recent_third) if recent_third else 0

    # Determine trend
    if recent_sv > second_sv > first_sv:
        trend = 'strong_improvement'
        trend_adj = 1.01  # +1% boost
    elif recent_sv > first_sv:
        trend = 'improving'
        trend_adj = 1.005  # +0.5% boost
    elif recent_sv < second_sv < first_sv:
        trend = 'declining'
        trend_adj = 0.985  # -1.5% penalty
    elif recent_sv < first_sv:
        trend = 'slight_decline'
        trend_adj = 0.995  # -0.5% penalty
    else:
        trend = 'stable'
        trend_adj = 1.0

    # Check for late-season fatigue (March/April)
    month = game_date.month
    if month in [3, 4]:
        trend_adj *= 0.995  # Additional -0.5% for late season

    monthly_perf = {
        'first_third_sv': round(first_sv, 3),
        'second_third_sv': round(second_sv, 3),
        'recent_third_sv': round(recent_sv, 3)
    }

    return trend, monthly_perf, trend_adj

def calculate_situational_performance(goalie_id, opponent_team_name, game_date):
    """
    IMPROVEMENT #4: Situational performance patterns
    Analyzes performance in specific situations
    Returns: (is_division_game, is_playoff_team, bounce_back_adj, situation_adj)

    Impact:
    - Strong bounce-back performer (after bad game): +2% SV%
    - Weak vs playoff teams: -1% SV%
    - Division rivalry boost: +0.5% SV%
    """
    # Check if this is a division matchup (using team stats)
    opponent = db_session.query(NHLTeamStats).filter_by(team_name=opponent_team_name).first()
    is_division = False  # Would need division mapping data
    is_playoff_team = False
    if opponent and opponent.wins:
        # Assume top 16 teams in wins are playoff-bound
        all_teams = db_session.query(NHLTeamStats).order_by(NHLTeamStats.wins.desc()).limit(16).all()
        is_playoff_team = opponent in all_teams

    # Check bounce-back ability (performance after allowing 4+ goals)
    # OPTIMIZED: Limit query to last 30 games instead of all games
    recent_games = db_session.query(NHLGoalieActuals).filter_by(
        goalie_id=goalie_id
    ).order_by(NHLGoalieActuals.game_date.desc()).limit(30).all()

    bounce_back_adj = 1.0
    if len(recent_games) >= 2:
        last_game = recent_games[0]
        # If last game was bad (4+ goals against), check bounce-back pattern
        if last_game.actual_goals_against >= 4:
            # Look at historical bounce-backs (only recent 30 games for performance)
            bad_games = [g for g in recent_games[1:] if g.actual_goals_against >= 4]

            if len(bad_games) >= 2:  # Need at least 2 bad games in history
                bounce_backs = []
                for bad_game in bad_games:
                    # Find next game after this bad game
                    bad_game_idx = recent_games.index(bad_game)
                    if bad_game_idx > 0:  # There's a game after
                        next_game = recent_games[bad_game_idx - 1]  # List is desc order
                        bounce_backs.append(next_game.actual_save_pct)

                if len(bounce_backs) >= 2:
                    avg_bounce_back = sum(bounce_backs) / len(bounce_backs)
                    goalie_season_avg = sum(g.actual_save_pct for g in recent_games[:10]) / min(10, len(recent_games))

                    if avg_bounce_back > goalie_season_avg + 0.02:
                        bounce_back_adj = 1.02  # Strong bounce-back performer
                    elif avg_bounce_back < goalie_season_avg - 0.02:
                        bounce_back_adj = 0.99  # Struggles after bad games

    # Situational adjustment
    situation_adj = 1.0
    # Simplified playoff team adjustment (removed heavy queries for performance)

    if is_division:
        situation_adj *= 1.005  # +0.5% rivalry boost

    return is_division, is_playoff_team, bounce_back_adj, situation_adj

def get_opponent_rolling_form(opponent_team_name, games_back=10):
    """
    IMPROVEMENT #5: Advanced opponent metrics - rolling offensive form
    Track opponent's recent offensive performance, not just season average
    Returns: (rolling_goals_pg, rolling_shots_pg, rolling_shooting_pct, form_adj)

    Impact:
    - Opponent on hot streak (scoring 4+ GPG recently): -1% SV%
    - Opponent in slump (<2 GPG recently): +1% SV%
    """
    # Get opponent's recent games
    opponent_games = db_session.query(NHLGameStats).filter(
        db.or_(
            NHLGameStats.home_team_name == opponent_team_name,
            NHLGameStats.away_team_name == opponent_team_name
        )
    ).order_by(NHLGameStats.game_date.desc()).limit(games_back).all()

    if not opponent_games:
        return None, None, None, 1.0

    total_goals = 0
    total_shots = 0

    for game in opponent_games:
        if game.home_team_name == opponent_team_name:
            total_goals += game.home_score
            total_shots += game.home_sog
        else:
            total_goals += game.away_score
            total_shots += game.away_sog

    rolling_goals_pg = total_goals / len(opponent_games)
    rolling_shots_pg = total_shots / len(opponent_games)
    rolling_shooting_pct = total_goals / total_shots if total_shots > 0 else 0

    # Adjust based on recent form
    form_adj = 1.0
    if rolling_goals_pg >= 4.0:
        form_adj = 0.99  # Hot offense: -1% SV%
    elif rolling_goals_pg >= 3.5:
        form_adj = 0.995  # Good offense: -0.5% SV%
    elif rolling_goals_pg <= 2.0:
        form_adj = 1.01  # Cold offense: +1% SV%
    elif rolling_goals_pg <= 2.5:
        form_adj = 1.005  # Struggling offense: +0.5% SV%

    return rolling_goals_pg, rolling_shots_pg, rolling_shooting_pct, form_adj

def calculate_confidence_from_historical_accuracy(goalie_id, opponent_team_name, predicted_saves, game_date):
    """
    IMPROVEMENT #3: Confidence calibration based on historical prediction accuracy
    OPTIMIZED: Use recent games only for performance
    Returns: calibrated_confidence (0-100)

    High confidence (90+): Goalie has 40+ games this season
    Medium confidence (70-89): Goalie has 20-39 games
    Low confidence (<70): Goalie has <20 games
    """
    # OPTIMIZED: Use simple game count instead of complex historical analysis
    # Get goalie's current season games
    goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()

    if not goalie:
        return 50

    games_played = goalie.games_played or 0

    # Base confidence on games played
    if games_played >= 40:
        confidence = 90
    elif games_played >= 30:
        confidence = 85
    elif games_played >= 20:
        confidence = 75
    elif games_played >= 10:
        confidence = 65
    else:
        confidence = 55

    # Boost confidence if we have historical data
    historical = db_session.query(NHLGoalieActuals).filter_by(goalie_id=goalie_id).limit(100).all()

    if len(historical) > 50:
        confidence += 5

    # Boost confidence if vs-team history exists
    vs_team_games = db_session.query(NHLGoalieActuals).filter_by(
        goalie_id=goalie_id,
        opponent_team_name=opponent_team_name
    ).limit(10).count()

    if vs_team_games >= 5:
        confidence += 3

    return min(100, confidence)

def predict_goalie_saves(goalie_id, goalie_name, opponent_team_name, game_date, is_home=None, goalie_team_name=None, game_time=None, venue_name=None):
    """
    Predict saves for a goalie based on 23 distinct factors:

    CORE FACTORS (1-11):
    1. Opponent's shots per game and offensive strength
    2. Goalie's save percentage (with home/away split)
    3. Goalie's recent form (IMPROVED: 10-game optimal window)
    4. Rest days (back-to-back, well-rested, extended rest)
    5. Team defensive rating
    6. Time of day adjustments
    7. Goalie momentum (hot/cold streaks)
    8. Opponent's goals per game and shooting percentage
    9. Venue-specific performance history
    10. Team familiarity (head-to-head matchups)
    11. Shot quality metrics (expected goals)

    ADVANCED FACTORS (12-18):
    12. Injury/health status (day-to-day, returning from injury)
    13. Workload/fatigue management (games in last 7/14 days)
    14. Opponent quality weighting (recent form vs. elite/weak teams)
    15. Special teams impact (opponent power play strength)
    16. Goalie vs. team historical performance
    17. Shot quality/distance metrics (high-danger chances)
    18. Defensive quality (shot blocking, defensive structure)

    HISTORICAL DATA IMPROVEMENTS (19-23):
    19. Season-long performance trends (improving/declining/stable)
    20. Bounce-back ability (performance after bad games)
    21. Playoff team adjustment (vs. top-16 teams)
    22. Opponent rolling form (last 10 games, not season average)
    23. Historical accuracy-based confidence calibration
    """

    # Get goalie stats
    goalie = db_session.query(NHLGoalie).filter_by(player_id=goalie_id).first()

    if not goalie or goalie.games_played < 3:
        print(f"  ⚠ {goalie_name}: Insufficient data (GP: {goalie.games_played if goalie else 0})")
        return None

    # Check injury status FIRST
    injury_status, games_since_injury, injury_adj = check_injury_status(goalie_id)

    if injury_adj is None:  # Goalie is out/IR
        print(f"  🚑 {goalie_name}: INJURED ({injury_status}) - Skip prediction")
        return None

    # Check workload/fatigue
    games_7d, games_14d, shots_7d, is_overworked, fatigue_adj = calculate_workload_fatigue(goalie_id, game_date)

    # Get opponent's shots per game (L10)
    opponent_shots = get_opponent_shots_per_game(opponent_team_name, games_back=10)

    # Get goalie's recent form with QUALITY WEIGHTING (opponent strength)
    quality_weighted_sv_pct, avg_opp_strength = calculate_quality_weighted_recent_form(goalie_id, games_back=5)

    # Also get standard weighted form for comparison
    recent_sv_pct, recent_avg_saves = calculate_goalie_recent_form(goalie_id, games_back=5, use_weighted=True)

    # Use quality-weighted if available, otherwise fall back
    if quality_weighted_sv_pct:
        recent_sv_pct = quality_weighted_sv_pct
    elif recent_sv_pct is None:
        # Fallback to season stats
        recent_sv_pct = goalie.save_pct
        recent_avg_saves = goalie.saves / goalie.games_played if goalie.games_played > 0 else 0

    # Get home/away split if available and specified
    home_away_sv_pct = None
    if is_home is not None:
        home_away_sv_pct = get_home_away_save_pct(goalie, is_home)

    # Weighted average of different metrics
    # 50% recent form (L5 weighted), 25% home/away split, 25% season
    if home_away_sv_pct and recent_sv_pct and goalie.save_pct:
        weighted_sv_pct = (recent_sv_pct * 0.50) + (home_away_sv_pct * 0.25) + (goalie.save_pct * 0.25)
    elif recent_sv_pct and goalie.save_pct:
        # No home/away data available, increase recent form weight
        weighted_sv_pct = (recent_sv_pct * 0.70) + (goalie.save_pct * 0.30)
    else:
        weighted_sv_pct = goalie.save_pct if goalie.save_pct else 0.900

    # Check rest days (replaces simple B2B check)
    days_rest, rest_category, sv_pct_adj, shots_adj_rest = check_rest_days(goalie, game_date)

    # Apply rest adjustment to save percentage
    weighted_sv_pct *= sv_pct_adj

    # Detect goalie momentum (hot/cold streaks)
    is_hot, is_cold, trend, momentum_adj = detect_goalie_momentum(goalie_id)

    # Apply momentum adjustment to save percentage
    weighted_sv_pct *= momentum_adj

    # Get opponent offensive strength (now includes xG)
    opp_goals_pg, opp_shooting_pct, offensive_impact, opp_xgf = get_opponent_offensive_strength(opponent_team_name)

    # Apply opponent offensive strength to save percentage
    # Strong offenses are harder to stop
    weighted_sv_pct *= offensive_impact

    # Get venue-specific adjustment
    venue_adj, venue_games, venue_sv_pct = get_venue_adjustment(goalie_id, venue_name)

    # Apply venue adjustment to save percentage
    weighted_sv_pct *= venue_adj

    # Get team familiarity adjustment
    fam_adj, games_vs_team, vs_team_sv_pct, vs_team_trend = get_team_familiarity_adjustment(goalie_id, opponent_team_name)

    # Apply familiarity adjustment to save percentage
    weighted_sv_pct *= fam_adj

    # Apply injury adjustment to save percentage
    weighted_sv_pct *= injury_adj

    # Apply workload/fatigue adjustment to save percentage
    weighted_sv_pct *= fatigue_adj

    # NEW FEATURE 3: Special teams adjustment
    opponent_pp_pct, special_teams_adj, pp_opps_pg = get_special_teams_adjustment(opponent_team_name)

    # NEW FEATURE 5: Goalie vs. team historical performance
    vs_team_sv_pct, games_vs_team, vs_team_adj = calculate_goalie_vs_team_history(goalie_id, opponent_team_name)

    # Apply vs-team historical adjustment to save percentage
    weighted_sv_pct *= vs_team_adj

    # NEW FEATURE 6: Shot quality adjustment (opponent)
    avg_shot_dist, high_danger_rate, shot_quality_adj = calculate_shot_quality_adjustment(opponent_team_name)

    # Apply shot quality adjustment to save percentage
    weighted_sv_pct *= shot_quality_adj

    # NEW FEATURE 2: Defensive quality impact (goalie's team)
    blocks_pg, def_quality_adj = calculate_defensive_quality_impact(goalie_team_name) if goalie_team_name else (None, 1.0)

    # Apply defensive quality adjustment to save percentage
    weighted_sv_pct *= def_quality_adj

    # IMPROVEMENT #2: Season-long trend analysis
    season_trend, monthly_perf, trend_adj = analyze_season_long_trends(goalie_id, game_date)

    # Apply trend adjustment to save percentage
    weighted_sv_pct *= trend_adj

    # IMPROVEMENT #4: Situational performance
    is_division, is_playoff_team, bounce_back_adj, situation_adj = calculate_situational_performance(goalie_id, opponent_team_name, game_date)

    # Apply situational adjustments to save percentage
    weighted_sv_pct *= bounce_back_adj
    weighted_sv_pct *= situation_adj

    # IMPROVEMENT #5: Opponent rolling form (replaces static season average)
    opp_rolling_goals, opp_rolling_shots, opp_rolling_sh_pct, rolling_form_adj = get_opponent_rolling_form(opponent_team_name)

    # Apply opponent rolling form adjustment to save percentage
    weighted_sv_pct *= rolling_form_adj

    # Get team defensive rating (affects opponent shots)
    if goalie_team_name:
        team_defense = get_team_defensive_rating(goalie_team_name)
        # Adjust opponent shots based on team defense
        # League average is ~30 shots. If team allows 27, that's good defense
        league_avg_shots = 30.0
        defense_factor = team_defense / league_avg_shots
        # Blend opponent offense (70%) with team defense (30%)
        opponent_shots = (opponent_shots * 0.70) + (team_defense * 0.30)

    # Use rolling shots if available (more accurate)
    if opp_rolling_shots:
        opponent_shots = (opponent_shots * 0.40) + (opp_rolling_shots * 0.60)  # Weight recent form 60%

    # Apply rest day adjustment to shots
    adjusted_opponent_shots = opponent_shots * shots_adj_rest

    # Apply special teams adjustment to shots (elite PP teams take more shots)
    adjusted_opponent_shots *= special_teams_adj

    # Apply time of day adjustment
    time_adjustment = get_time_of_day_adjustment(game_time)
    adjusted_opponent_shots *= time_adjustment

    # Predict saves
    predicted_shots_against = adjusted_opponent_shots
    predicted_saves = predicted_shots_against * weighted_sv_pct

    # IMPROVEMENT #3: Historical accuracy-based confidence (replaces simple formula)
    base_confidence = calculate_confidence_from_historical_accuracy(goalie_id, opponent_team_name, predicted_saves, game_date)

    # Adjust confidence based on data quality and situation
    confidence = base_confidence

    # Reduce confidence for back-to-back or extended rest
    if rest_category == 'back_to_back':
        confidence *= 0.9
    elif rest_category == 'extended_rest':
        confidence *= 0.95

    # Boost confidence for strong trends
    if season_trend == 'strong_improvement':
        confidence = min(100, confidence + 3)
    elif season_trend == 'declining':
        confidence *= 0.95

    confidence = min(100, max(50, confidence))  # Keep between 50-100

    return {
        'goalie_id': goalie_id,
        'goalie_name': goalie_name,
        'opponent_team': opponent_team_name,
        'game_date': game_date,
        'predicted_saves': round(predicted_saves, 1),
        'predicted_shots_against': round(predicted_shots_against, 1),
        'predicted_save_pct': round(weighted_sv_pct, 3),
        'confidence': confidence,
        'goalie_games_played': goalie.games_played,
        'goalie_season_sv_pct': round(goalie.save_pct, 3),
        'goalie_recent_sv_pct': round(recent_sv_pct, 3) if recent_sv_pct else None,
        'opponent_shots_avg': round(opponent_shots, 1),
        'is_back_to_back': (rest_category == 'back_to_back'),
        'rest_category': rest_category,
        'days_rest': days_rest,
        'home_away_sv_pct': round(home_away_sv_pct, 3) if home_away_sv_pct else None,
        'is_home': is_home,
        # Momentum indicators
        'is_hot_streak': is_hot,
        'is_cold_streak': is_cold,
        'sv_pct_trend': round(trend, 3) if trend else 0.0,
        # Opponent offensive strength
        'opponent_goals_pg': round(opp_goals_pg, 2),
        'opponent_shooting_pct': round(opp_shooting_pct, 3),
        'opponent_xgf_per_game': round(opp_xgf, 2) if opp_xgf else None,
        # Venue-specific performance
        'venue_name': venue_name,
        'venue_games': venue_games,
        'venue_sv_pct': round(venue_sv_pct, 3) if venue_sv_pct else None,
        'venue_adjustment': round(venue_adj, 3) if venue_adj != 1.0 else None,
        # Team familiarity
        'games_vs_opponent': games_vs_team,
        'sv_pct_vs_opponent': round(vs_team_sv_pct, 3) if vs_team_sv_pct else None,
        'vs_opponent_trend': vs_team_trend,
        'familiarity_adjustment': round(fam_adj, 3) if fam_adj != 1.0 else None,
        # Injury/Health status
        'injury_status': injury_status,
        'games_since_injury': games_since_injury,
        'injury_adjustment': round(injury_adj, 3) if injury_adj != 1.0 else None,
        # Workload/Fatigue
        'games_in_last_7_days': games_7d,
        'games_in_last_14_days': games_14d,
        'shots_faced_last_7_days': shots_7d,
        'is_overworked': is_overworked,
        'fatigue_adjustment': round(fatigue_adj, 3) if fatigue_adj != 1.0 else None,
        # Opponent quality
        'avg_opponent_strength_L5': round(avg_opp_strength, 1) if avg_opp_strength else None,
        # NEW: Special teams
        'opponent_pp_pct': round(opponent_pp_pct, 3) if opponent_pp_pct else None,
        'special_teams_adjustment': round(special_teams_adj, 3) if special_teams_adj != 1.0 else None,
        # NEW: Goalie vs. team history
        'goalie_career_vs_opponent_sv_pct': round(vs_team_sv_pct, 3) if vs_team_sv_pct else None,
        'career_games_vs_opponent': games_vs_team,
        'vs_team_historical_adjustment': round(vs_team_adj, 3) if vs_team_adj != 1.0 else None,
        # NEW: Shot quality metrics
        'opponent_avg_shot_distance': round(avg_shot_dist, 1) if avg_shot_dist else None,
        'opponent_high_danger_rate': round(high_danger_rate, 2) if high_danger_rate else None,
        'shot_quality_adjustment': round(shot_quality_adj, 3) if shot_quality_adj != 1.0 else None,
        # NEW: Defensive quality
        'team_blocked_shots_pg': round(blocks_pg, 1) if blocks_pg else None,
        'defensive_quality_adjustment': round(def_quality_adj, 3) if def_quality_adj != 1.0 else None,
        # IMPROVEMENT #2: Season-long trends
        'season_trend': season_trend,
        'season_trend_adjustment': round(trend_adj, 3) if trend_adj != 1.0 else None,
        'monthly_performance': monthly_perf,
        # IMPROVEMENT #4: Situational performance
        'is_playoff_opponent': is_playoff_team,
        'bounce_back_adjustment': round(bounce_back_adj, 3) if bounce_back_adj != 1.0 else None,
        'situational_adjustment': round(situation_adj, 3) if situation_adj != 1.0 else None,
        # IMPROVEMENT #5: Opponent rolling form
        'opponent_rolling_goals_pg': round(opp_rolling_goals, 2) if opp_rolling_goals else None,
        'opponent_rolling_shots_pg': round(opp_rolling_shots, 1) if opp_rolling_shots else None,
        'opponent_rolling_form_adjustment': round(rolling_form_adj, 3) if rolling_form_adj != 1.0 else None,
    }

def backtest_model(days_back=30):
    """
    Test model accuracy on recent historical games
    """
    print("="*70)
    print("BACKTESTING GOALIE SAVES MODEL")
    print("="*70)

    # Get recent games with goalie data
    cutoff_date = datetime.now().date()

    recent_actuals = db_session.query(NHLGoalieActuals).filter(
        NHLGoalieActuals.game_date >= datetime(2025, 9, 1).date()
    ).order_by(
        NHLGoalieActuals.game_date.desc()
    ).limit(200).all()

    print(f"\nTesting on {len(recent_actuals)} recent goalie performances...\n")

    predictions = []
    errors = []
    correct_over_under = 0
    total_tested = 0

    for actual in recent_actuals:
        # Make prediction
        pred = predict_goalie_saves(
            actual.goalie_id,
            actual.goalie_name,
            actual.opponent_team_name,
            actual.game_date
        )

        if not pred:
            continue

        # Calculate error
        error = abs(pred['predicted_saves'] - actual.actual_saves)
        errors.append(error)

        # Check if we predicted over/under correctly
        # Using a typical O/U line of 26.5 saves
        line = 26.5
        pred_over = pred['predicted_saves'] > line
        actual_over = actual.actual_saves > line

        if pred_over == actual_over:
            correct_over_under += 1

        total_tested += 1

        predictions.append({
            'date': actual.game_date,
            'goalie': actual.goalie_name,
            'opponent': actual.opponent_team_name,
            'predicted': pred['predicted_saves'],
            'actual': actual.actual_saves,
            'error': error,
            'pred_over': pred_over,
            'actual_over': actual_over,
            'correct': pred_over == actual_over
        })

    if not errors:
        print("⚠ No predictions to test")
        return

    # Calculate metrics
    mean_error = np.mean(errors)
    median_error = np.median(errors)
    accuracy = (correct_over_under / total_tested) * 100

    print("="*70)
    print("BACKTEST RESULTS")
    print("="*70)
    print(f"Games Tested: {total_tested}")
    print(f"Mean Absolute Error: {mean_error:.2f} saves")
    print(f"Median Absolute Error: {median_error:.2f} saves")
    print(f"Over/Under Accuracy (26.5 line): {accuracy:.1f}%")
    print()

    # Show best and worst predictions
    sorted_preds = sorted(predictions, key=lambda x: x['error'])

    print("🎯 BEST PREDICTIONS (lowest error):")
    print("-"*70)
    for p in sorted_preds[:5]:
        result = "✓" if p['correct'] else "✗"
        print(f"{result} {p['goalie']:20} vs {p['opponent']:20} Pred: {p['predicted']:.1f} Actual: {p['actual']} (Error: {p['error']:.1f})")

    print("\n❌ WORST PREDICTIONS (highest error):")
    print("-"*70)
    for p in sorted_preds[-5:]:
        result = "✓" if p['correct'] else "✗"
        print(f"{result} {p['goalie']:20} vs {p['opponent']:20} Pred: {p['predicted']:.1f} Actual: {p['actual']} (Error: {p['error']:.1f})")

    print("\n" + "="*70)

    # Performance by confidence
    high_conf = [p for p in predictions if p['predicted'] > 28 or p['predicted'] < 24]
    if high_conf:
        high_conf_correct = sum(1 for p in high_conf if p['correct'])
        high_conf_acc = (high_conf_correct / len(high_conf)) * 100
        print(f"High Confidence Picks (>28 or <24 saves): {high_conf_acc:.1f}% accuracy ({len(high_conf)} bets)")

    print("="*70)

def generate_todays_predictions():
    """
    Generate predictions for today's games
    (This would fetch today's schedule and starting goalies)
    """
    print("\n" + "="*70)
    print("TODAY'S PREDICTIONS")
    print("="*70)
    print("\n⚠ Note: This requires today's starting goalie announcements")
    print("In production, this would:")
    print("  1. Fetch today's NHL schedule")
    print("  2. Get confirmed starting goalies")
    print("  3. Generate predictions for each goalie")
    print("  4. Compare to betting lines")
    print("  5. Output best bets with confidence scores")
    print("\n" + "="*70)

def main():
    
        print("\n" + "="*70)
        print("NHL GOALIE SAVES PREDICTION MODEL")
        print("="*70)

        # Show data status
        total_games = db_session.query(NHLGameStats).count()
        total_actuals = db_session.query(NHLGoalieActuals).count()
        total_goalies = db_session.query(NHLGoalie).filter(NHLGoalie.games_played > 0).count()

        print(f"\n📊 Training Data:")
        print(f"  Games: {total_games}")
        print(f"  Goalie Performances: {total_actuals}")
        print(f"  Goalies: {total_goalies}")

        # Run backtest
        print("\n")
        backtest_model(days_back=30)

        # Show example prediction
        print("\n" + "="*70)
        print("EXAMPLE PREDICTION")
        print("="*70)

        # Get a top goalie
        top_goalie = db_session.query(NHLGoalie).filter(
            NHLGoalie.games_played >= 10
        ).order_by(
            NHLGoalie.saves.desc()
        ).first()

        if top_goalie:
            # Get a high-shot team
            high_shot_team = db_session.query(NHLTeamStats).filter(
                NHLTeamStats.games_played > 0
            ).order_by(
                NHLTeamStats.shots_for_per_game.desc()
            ).first()

            if high_shot_team:
                pred = predict_goalie_saves(
                    top_goalie.player_id,
                    top_goalie.name,
                    high_shot_team.team_name,
                    date.today()
                )

                if pred:
                    print(f"\n{pred['goalie_name']} vs {pred['opponent_team']}:")
                    print(f"  Predicted Saves: {pred['predicted_saves']}")
                    print(f"  Expected Shots Against: {pred['predicted_shots_against']}")
                    print(f"  Goalie SV% (Season): {pred['goalie_season_sv_pct']}")
                    print(f"  Goalie SV% (Recent): {pred['goalie_recent_sv_pct']}")
                    print(f"  Opponent Avg Shots: {pred['opponent_shots_avg']}")
                    print(f"  Confidence: {pred['confidence']}%")
                    print(f"\n  Betting Recommendation:")
                    if pred['predicted_saves'] > 27.5:
                        print(f"    OVER 26.5 or 27.5 saves")
                    elif pred['predicted_saves'] < 25.5:
                        print(f"    UNDER 26.5 or 27.5 saves")
                    else:
                        print(f"    PASS - Too close to call")

        print("\n" + "="*70)

if __name__ == "__main__":
    main()
