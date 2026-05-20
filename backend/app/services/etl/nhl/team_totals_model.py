"""
NHL Team Total Goals Prediction Model

Predicts total goals (over/under) for NHL games using:
- Team offensive strength (goals for per game)
- Team defensive strength (goals against per game)
- Home/away splits
- Special teams matchup (PP vs PK)
- Recent form (last 10 games)
- Shooting percentage and pace
"""

import sys
import os

from app.services.etl.nhl._db import db_session
from app.models.predictions_models import NHLTeamStats
from datetime import datetime, date


def predict_team_total_goals(home_team_name, away_team_name, game_date=None):
    """
    Predict total goals for an NHL game

    Args:
        home_team_name: Name of home team
        away_team_name: Name of away team
        game_date: Date of the game (defaults to today)

    Returns:
        dict with prediction details
    """
    if game_date is None:
        game_date = date.today()

    # Get team data
    home_team = db_session.query(NHLTeamStats).filter_by(team_name=home_team_name).first()
    away_team = db_session.query(NHLTeamStats).filter_by(team_name=away_team_name).first()

    if not home_team or not away_team:
        return {'error': 'Team not found'}

    # === HOME TEAM EXPECTED GOALS ===

    # Start with home offense vs away defense
    home_base_goals = (home_team.goals_for_per_game or 0) * 0.5 + \
                      (away_team.goals_against_per_game or 0) * 0.5

    # Apply home ice advantage
    home_ice_boost = 1.10  # 10% boost for home team

    home_expected = home_base_goals * home_ice_boost

    # Special teams adjustment
    # Good PP vs weak PK = more goals
    if home_team.power_play_pct and away_team.penalty_kill_pct:
        pp_matchup = home_team.power_play_pct / (1 - away_team.penalty_kill_pct + 0.01)
        if pp_matchup > 1.3:  # Strong PP vs weak PK
            home_expected *= 1.08  # +8% boost
        elif pp_matchup < 0.7:  # Weak PP vs strong PK
            home_expected *= 0.92  # -8% reduction

    # Shooting percentage adjustment
    if home_team.shooting_pct:
        league_avg_shooting = 0.10  # 10%
        if home_team.shooting_pct > league_avg_shooting * 1.15:  # Hot shooting
            home_expected *= 1.05
        elif home_team.shooting_pct < league_avg_shooting * 0.85:  # Cold shooting
            home_expected *= 0.95

    # === AWAY TEAM EXPECTED GOALS ===

    # Start with away offense vs home defense
    away_base_goals = (away_team.goals_for_per_game or 0) * 0.5 + \
                      (home_team.goals_against_per_game or 0) * 0.5

    # Away teams score slightly less
    away_penalty = 0.95  # -5% for away team

    away_expected = away_base_goals * away_penalty

    # Special teams adjustment
    if away_team.power_play_pct and home_team.penalty_kill_pct:
        pp_matchup = away_team.power_play_pct / (1 - home_team.penalty_kill_pct + 0.01)
        if pp_matchup > 1.3:
            away_expected *= 1.08
        elif pp_matchup < 0.7:
            away_expected *= 0.92

    # Shooting percentage adjustment
    if away_team.shooting_pct:
        if away_team.shooting_pct > league_avg_shooting * 1.15:
            away_expected *= 1.05
        elif away_team.shooting_pct < league_avg_shooting * 0.85:
            away_expected *= 0.95

    # === TOTAL GOALS CALCULATION ===

    total_goals = home_expected + away_expected

    # Pace adjustment (combined shots)
    home_shots = home_team.shots_for_per_game or 0
    away_shots = away_team.shots_for_per_game or 0
    combined_shots = home_shots + away_shots

    if combined_shots > 64:  # High pace game
        total_goals *= 1.05  # +5%
    elif combined_shots < 56:  # Low pace game
        total_goals *= 0.95  # -5%

    # Recent form adjustment (use last 10 games data)
    recent_form_adj = 1.0

    home_recent_gpg = home_team.last_10_goals_for_per_game or home_team.goals_for_per_game or 0
    away_recent_gpg = away_team.last_10_goals_for_per_game or away_team.goals_for_per_game or 0

    # If both teams are hot offensively
    if home_recent_gpg > (home_team.goals_for_per_game or 0) * 1.15 and \
       away_recent_gpg > (away_team.goals_for_per_game or 0) * 1.15:
        recent_form_adj = 1.08  # Both teams hot
    # If both teams are cold offensively
    elif home_recent_gpg < (home_team.goals_for_per_game or 0) * 0.85 and \
         away_recent_gpg < (away_team.goals_for_per_game or 0) * 0.85:
        recent_form_adj = 0.92  # Both teams cold

    total_goals *= recent_form_adj

    # Calculate confidence based on multiple factors
    home_games = home_team.games_played or 0
    away_games = away_team.games_played or 0
    min_games = min(home_games, away_games)

    # Base confidence on sample size (more granular)
    if min_games >= 50:
        confidence = 85
    elif min_games >= 40:
        confidence = 80
    elif min_games >= 30:
        confidence = 75
    elif min_games >= 20:
        confidence = 70
    elif min_games >= 15:
        confidence = 68
    elif min_games >= 10:
        confidence = 65
    elif min_games >= 5:
        confidence = 60
    else:
        confidence = 55

    # Adjust based on team consistency (standard deviation of scoring)
    # Teams with more consistent scoring get higher confidence
    home_consistency = 1.0
    away_consistency = 1.0

    # If teams have big gaps between recent and season averages, adjust confidence
    if home_team.last_10_goals_for_per_game and home_team.goals_for_per_game:
        home_variance = abs(home_team.last_10_goals_for_per_game - home_team.goals_for_per_game)
        if home_variance > 1.0:
            home_consistency = 0.85  # Very inconsistent
        elif home_variance > 0.5:
            home_consistency = 0.92  # Somewhat inconsistent
        elif home_variance < 0.15:
            home_consistency = 1.08  # Very consistent, boost confidence

    if away_team.last_10_goals_for_per_game and away_team.goals_for_per_game:
        away_variance = abs(away_team.last_10_goals_for_per_game - away_team.goals_for_per_game)
        if away_variance > 1.0:
            away_consistency = 0.85  # Very inconsistent
        elif away_variance > 0.5:
            away_consistency = 0.92  # Somewhat inconsistent
        elif away_variance < 0.15:
            away_consistency = 1.08  # Very consistent, boost confidence

    # Average consistency factor
    avg_consistency = (home_consistency + away_consistency) / 2
    confidence = int(confidence * avg_consistency)

    # Adjust confidence for high/low scoring matchups
    if total_goals > 7.0:
        confidence += 5  # Very high scoring = more predictable
    elif total_goals > 6.5:
        confidence += 3  # High scoring = more predictable
    elif total_goals < 4.5:
        confidence -= 5  # Very low scoring = less predictable
    elif total_goals < 5.0:
        confidence -= 3  # Low scoring = less predictable

    # Boost confidence when both teams are on hot/cold streaks
    if abs(recent_form_adj - 1.0) > 0.07:
        confidence += 4  # Strong trends = more predictable
    elif abs(recent_form_adj - 1.0) > 0.05:
        confidence += 2  # Moderate trends = somewhat more predictable

    # Cap confidence at 90 and floor at 55
    confidence = max(55, min(90, confidence))

    # Determine over/under recommendation
    # Typical NHL total is 6.0 goals
    typical_total = 6.0
    ou_line = round(total_goals * 2) / 2  # Round to nearest 0.5

    if total_goals > typical_total * 1.10:
        recommendation = f"OVER {ou_line}"
    elif total_goals < typical_total * 0.90:
        recommendation = f"UNDER {ou_line}"
    else:
        recommendation = "NEUTRAL"

    # Build result
    result = {
        'game_date': game_date,
        'home_team': home_team_name,
        'away_team': away_team_name,

        # Predictions
        'predicted_total_goals': round(total_goals, 2),
        'predicted_home_goals': round(home_expected, 2),
        'predicted_away_goals': round(away_expected, 2),
        'suggested_ou_line': ou_line,
        'recommendation': recommendation,
        'confidence': confidence,

        # Supporting metrics
        'home_offense_rating': round(home_team.goals_for_per_game or 0, 2),
        'away_offense_rating': round(away_team.goals_for_per_game or 0, 2),
        'home_defense_rating': round(home_team.goals_against_per_game or 0, 2),
        'away_defense_rating': round(away_team.goals_against_per_game or 0, 2),
        'combined_pace': round(combined_shots, 1),
        'home_pp_pct': round((home_team.power_play_pct or 0) * 100, 1),
        'away_pp_pct': round((away_team.power_play_pct or 0) * 100, 1),
        'home_pk_pct': round((home_team.penalty_kill_pct or 0) * 100, 1),
        'away_pk_pct': round((away_team.penalty_kill_pct or 0) * 100, 1),
    }

    return result


def generate_daily_totals_predictions(game_date=None):
    """
    Generate total goals predictions for sample matchups
    In production, would get actual scheduled games for the date
    """
    if game_date is None:
        game_date = date.today()

    print(f"\n{'='*80}")
    print(f"NHL TEAM TOTAL GOALS PREDICTIONS - {game_date}")
    print(f"{'='*80}\n")

    # Sample matchups (in real use, would get from actual schedule)
    matchups = [
        ('Toronto', 'Boston'),
        ('Vegas', 'Colorado'),
        ('Tampa Bay', 'Florida'),
        ('Edmonton', 'Calgary'),
        ('New York Rangers', 'New Jersey'),
        ('Dallas', 'Minnesota'),
        ('Carolina', 'Pittsburgh'),
        ('Los Angeles', 'Seattle'),
    ]

    predictions = []

    for home, away in matchups:
        pred = predict_team_total_goals(home, away, game_date)

        if 'error' not in pred:
            predictions.append(pred)

            # Display prediction
            print(f"{pred['away_team']:25} @ {pred['home_team']:25}")
            print(f"  Predicted Total: {pred['predicted_total_goals']:.1f} goals")
            print(f"    Home: {pred['predicted_home_goals']:.1f} | Away: {pred['predicted_away_goals']:.1f}")
            print(f"  Suggested O/U Line: {pred['suggested_ou_line']}")
            print(f"  Recommendation: {pred['recommendation']:15} | Confidence: {pred['confidence']}%")

            # Show key factors
            print(f"\n  Offense: {pred['home_team'][:15]:15} {pred['home_offense_rating']:.2f} GPG | "
                  f"{pred['away_team'][:15]:15} {pred['away_offense_rating']:.2f} GPG")
            print(f"  Defense: {pred['home_team'][:15]:15} {pred['home_defense_rating']:.2f} GA/G | "
                  f"{pred['away_team'][:15]:15} {pred['away_defense_rating']:.2f} GA/G")
            print(f"  Special Teams: {pred['home_team'][:15]:15} PP {pred['home_pp_pct']:.1f}% / PK {pred['home_pk_pct']:.1f}%")
            print(f"                 {pred['away_team'][:15]:15} PP {pred['away_pp_pct']:.1f}% / PK {pred['away_pk_pct']:.1f}%")
            print(f"  Pace: {pred['combined_pace']:.1f} combined shots/game")
            print()

    print(f"{'='*80}")
    print(f"Generated {len(predictions)} predictions")
    print(f"{'='*80}\n")

    return predictions


if __name__ == "__main__":
    
        # Test the model
        print("\nTesting NHL Team Total Goals Prediction Model\n")

        # Test with a specific matchup
        print(f"=== SINGLE PREDICTION TEST ===")
        pred = predict_team_total_goals('Toronto', 'Boston')

        print(f"\nMatchup: {pred['away_team']} @ {pred['home_team']}")
        print(f"\nPredicted Total: {pred['predicted_total_goals']:.2f} goals")
        print(f"  Home expected: {pred['predicted_home_goals']:.2f}")
        print(f"  Away expected: {pred['predicted_away_goals']:.2f}")
        print(f"\nSuggested O/U Line: {pred['suggested_ou_line']}")
        print(f"Recommendation: {pred['recommendation']}")
        print(f"Confidence: {pred['confidence']}%")

        print(f"\nKey Metrics:")
        print(f"  Home offense: {pred['home_offense_rating']:.2f} GPG")
        print(f"  Away offense: {pred['away_offense_rating']:.2f} GPG")
        print(f"  Home defense: {pred['home_defense_rating']:.2f} GA/G")
        print(f"  Away defense: {pred['away_defense_rating']:.2f} GA/G")
        print(f"  Combined pace: {pred['combined_pace']:.1f} shots/game")
        print()

        # Generate daily predictions
        generate_daily_totals_predictions()
