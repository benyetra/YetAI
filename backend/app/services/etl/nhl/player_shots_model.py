"""
NHL Player Shots Prediction Model

Predicts shots on goal for individual players using:
- Player season average shots/game
- Ice time per game (more ice = more opportunities)
- Opponent shots allowed
- Opponent blocked shots (defensive quality)
- Position adjustments (forwards vs defense)
"""

import sys
import os

from app.services.etl.nhl._db import db_session
from app.models.predictions_models import (
    NHLPlayer,
    NHLTeamStats,
    NHLPlayerShotsPredictions,
)
from datetime import datetime, date


def predict_player_shots(player_id, opponent_team_name, game_date=None, is_home=True):
    """
    Predict shots on goal for a player in a specific game

    Args:
        player_id: NHL player ID
        opponent_team_name: Name of opponent team
        game_date: Date of the game (defaults to today)
        is_home: Whether player's team is home

    Returns:
        dict with prediction details
    """
    if game_date is None:
        game_date = date.today()

    # Get player data
    player = db_session.query(NHLPlayer).filter_by(player_id=player_id).first()

    if not player:
        return {"error": "Player not found"}

    # Get opponent data
    opponent = (
        db_session.query(NHLTeamStats).filter_by(team_name=opponent_team_name).first()
    )

    if not opponent:
        return {"error": "Opponent team not found"}

    # Baseline: player's season average
    baseline_shots = player.shots_per_game or 0

    if baseline_shots == 0:
        return {"error": "Player has no shot data"}

    # Start with baseline
    predicted_shots = baseline_shots

    # FACTOR 1: Ice time adjustment
    # More ice time = more shot opportunities
    # League average is ~1000 seconds (16:40), adjust from there
    ice_time_adj = 1.0
    if player.toi_per_game:
        league_avg_toi = 1000  # seconds
        if player.toi_per_game > league_avg_toi * 1.2:  # 20%+ more ice time
            ice_time_adj = 1.15  # +15% shots
        elif player.toi_per_game > league_avg_toi * 1.1:  # 10%+ more ice time
            ice_time_adj = 1.08  # +8% shots
        elif player.toi_per_game < league_avg_toi * 0.8:  # 20%+ less ice time
            ice_time_adj = 0.85  # -15% shots
        elif player.toi_per_game < league_avg_toi * 0.9:  # 10%+ less ice time
            ice_time_adj = 0.92  # -8% shots

    predicted_shots *= ice_time_adj

    # FACTOR 2: Opponent shots allowed
    # Teams that allow more shots = easier to get shots off
    opponent_shots_adj = 1.0
    if opponent.shots_against_per_game:
        league_avg_shots_against = 30.0  # NHL average
        if opponent.shots_against_per_game > 32:  # Allows lots of shots
            opponent_shots_adj = 1.10  # +10% easier to shoot
        elif opponent.shots_against_per_game > 31:
            opponent_shots_adj = 1.05  # +5%
        elif opponent.shots_against_per_game < 28:  # Stingy defense
            opponent_shots_adj = 0.90  # -10% harder to shoot
        elif opponent.shots_against_per_game < 29:
            opponent_shots_adj = 0.95  # -5%

    predicted_shots *= opponent_shots_adj

    # FACTOR 3: Blocked shots (defensive pressure)
    # Teams that block more shots make it harder to get shots through
    blocks_adj = 1.0
    if opponent.blocked_shots_per_game:
        if opponent.blocked_shots_per_game > 17:  # Heavy shot blocking
            blocks_adj = 0.92  # -8% (harder to get shots through)
        elif opponent.blocked_shots_per_game > 16:
            blocks_adj = 0.96  # -4%
        elif opponent.blocked_shots_per_game < 14:  # Light blocking
            blocks_adj = 1.08  # +8% (easier to get shots through)
        elif opponent.blocked_shots_per_game < 15:
            blocks_adj = 1.04  # +4%

    predicted_shots *= blocks_adj

    # FACTOR 4: Position adjustment
    # Forwards typically get more shots than defensemen
    position_adj = 1.0
    if player.position == "D":
        # Defensemen typically get 20-30% fewer shots
        position_adj = 0.75

    predicted_shots *= position_adj

    # FACTOR 5: Home ice advantage
    # Slight boost for home games (more offensive zone time)
    home_adj = 1.0
    if is_home:
        home_adj = 1.05  # +5% for home ice

    predicted_shots *= home_adj

    # Calculate confidence based on sample size
    games_played = player.games_played or 0
    if games_played >= 40:
        confidence = 85  # High confidence
    elif games_played >= 20:
        confidence = 75  # Medium confidence
    elif games_played >= 10:
        confidence = 65  # Lower confidence
    else:
        confidence = 50  # Low confidence (small sample)

    # Adjust confidence based on ice time consistency
    # Players with very high or very low ice time are more predictable
    if player.toi_per_game:
        if player.toi_per_game > 1200 or player.toi_per_game < 600:
            confidence += 5  # More predictable role

    # Build prediction result
    result = {
        "player_id": player.player_id,
        "player_name": player.name,
        "team_name": player.team_name,
        "opponent_name": opponent_team_name,
        "game_date": game_date,
        "is_home": is_home,
        # Prediction
        "predicted_shots": round(predicted_shots, 2),
        "baseline_shots": round(baseline_shots, 2),
        "confidence": confidence,
        # Adjustments applied
        "ice_time_adjustment": round(ice_time_adj, 3),
        "opponent_shots_adjustment": round(opponent_shots_adj, 3),
        "blocks_adjustment": round(blocks_adj, 3),
        "position_adjustment": round(position_adj, 3),
        "home_ice_adjustment": round(home_adj, 3),
        # Supporting data
        "player_toi_per_game": player.toi_per_game,
        "player_position": player.position,
        "player_games_played": games_played,
        "opponent_shots_against_pg": opponent.shots_against_per_game,
        "opponent_blocks_pg": opponent.blocked_shots_per_game,
    }

    return result


def generate_daily_player_predictions(game_date=None):
    """
    Generate predictions for all active players for a given date
    This would typically be run daily to get predictions for upcoming games

    For now, returns predictions for top shot-getters vs sample opponents
    """
    if game_date is None:
        game_date = date.today()

    print(f"\n{'='*80}")
    print(f"NHL PLAYER SHOTS PREDICTIONS - {game_date}")
    print(f"{'='*80}\n")

    # Get top players by shots
    top_players = (
        db_session.query(NHLPlayer)
        .filter(NHLPlayer.shots > 100)
        .order_by(NHLPlayer.shots.desc())
        .limit(20)
        .all()
    )

    # Sample opponents (in real use, would get from actual schedule)
    sample_opponents = ["Boston", "Toronto", "Tampa Bay", "Vegas", "Colorado"]

    predictions = []

    for i, player in enumerate(top_players[:10]):  # Top 10 for demo
        # Rotate through opponents
        opponent = sample_opponents[i % len(sample_opponents)]

        pred = predict_player_shots(
            player_id=player.player_id,
            opponent_team_name=opponent,
            game_date=game_date,
            is_home=(i % 2 == 0),  # Alternate home/away
        )

        if "error" not in pred:
            predictions.append(pred)

            # Display prediction
            print(f"{pred['player_name']:25} vs {pred['opponent_name']:20}")
            print(
                f"  {'Home' if pred['is_home'] else 'Away':4} | "
                f"Predicted: {pred['predicted_shots']:.1f} SOG | "
                f"Season Avg: {pred['baseline_shots']:.1f} | "
                f"Confidence: {pred['confidence']}%"
            )

            # Show key adjustments
            if pred["ice_time_adjustment"] != 1.0:
                print(
                    f"  📊 Ice time: {pred['ice_time_adjustment']:.2f}x "
                    f"({pred['player_toi_per_game']:.0f} sec/game)"
                )

            if pred["opponent_shots_adjustment"] != 1.0:
                print(
                    f"  🎯 Opponent allows: {pred['opponent_shots_against_pg']:.1f} shots/game "
                    f"({pred['opponent_shots_adjustment']:.2f}x)"
                )

            if pred["blocks_adjustment"] != 1.0:
                print(
                    f"  🛡️  Opponent blocks: {pred['opponent_blocks_pg']:.1f}/game "
                    f"({pred['blocks_adjustment']:.2f}x)"
                )

            print()

    print(f"{'='*80}")
    print(f"Generated {len(predictions)} predictions")
    print(f"{'='*80}\n")

    return predictions


if __name__ == "__main__":

    # Test the model
    print("\nTesting NHL Player Shots Prediction Model\n")

    # Test with a specific player
    player = db_session.query(NHLPlayer).filter(NHLPlayer.shots > 200).first()

    if player:
        print(f"=== SINGLE PREDICTION TEST ===")
        print(f"Player: {player.name}")
        print(
            f"Season stats: {player.shots} shots in {player.games_played} GP ({player.shots_per_game:.2f}/game)\n"
        )

        pred = predict_player_shots(
            player_id=player.player_id, opponent_team_name="Boston", is_home=True
        )

        print(f"Prediction vs Boston (Home):")
        print(f"  Predicted shots: {pred['predicted_shots']:.1f}")
        print(f"  Baseline: {pred['baseline_shots']:.1f}")
        print(f"  Confidence: {pred['confidence']}%")
        print(f"\nAdjustments:")
        print(f"  Ice time: {pred['ice_time_adjustment']:.3f}x")
        print(f"  Opponent defense: {pred['opponent_shots_adjustment']:.3f}x")
        print(f"  Shot blocking: {pred['blocks_adjustment']:.3f}x")
        print(f"  Position: {pred['position_adjustment']:.3f}x")
        print(f"  Home ice: {pred['home_ice_adjustment']:.3f}x")
        print()

    # Generate daily predictions
    generate_daily_player_predictions()
