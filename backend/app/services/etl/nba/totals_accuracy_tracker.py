"""NBA totals accuracy tracking — port of YetiBets totals_accuracy_tracker.py."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import requests

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.predictions_models import (
    NBATotalsAccuracy,
    NBATotalsActuals,
    NBATotalsProjections,
    RecentGames,
    TeamRoster,
)
from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)

db = None


def _today():
    return now_eastern().date()


def fetch_game_scores_from_api(game_date: date) -> List[Dict]:
    """
    Fetch game scores for a specific date from API-Sports.
    Returns list of game results.
    """
    api_key = settings.NBA_API_KEY or os.getenv('NBA_API_KEY')
    if not api_key:
        logger.warning("API_SPORTS_KEY not set - cannot fetch scores")
        return []

    try:
        url = "https://v1.basketball.api-sports.io/games"
        headers = {
            'x-rapidapi-key': api_key,
            'x-rapidapi-host': 'v1.basketball.api-sports.io'
        }
        params = {
            'date': game_date.strftime('%Y-%m-%d'),
            'league': '12',  # NBA
            'season': '2024-2025'
        }

        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            logger.error(f"API request failed: {response.status_code}")
            return []

        data = response.json()
        games = data.get('response', [])

        results = []
        for game in games:
            if game.get('status', {}).get('short') != 'FT':  # Only finished games
                continue

            home_team = game.get('teams', {}).get('home', {}).get('name', '')
            away_team = game.get('teams', {}).get('away', {}).get('name', '')
            home_score = game.get('scores', {}).get('home', {}).get('total', 0)
            away_score = game.get('scores', {}).get('away', {}).get('total', 0)

            if home_score and away_score:
                results.append({
                    'home_team': home_team,
                    'away_team': away_team,
                    'home_score': home_score,
                    'away_score': away_score,
                    'total': home_score + away_score
                })

        logger.info(f"Fetched {len(results)} completed games for {game_date}")
        return results

    except Exception as e:
        logger.error(f"Error fetching game scores: {e}")
        return []


def calculate_totals_from_player_data(game_date: date) -> List[Dict]:
    """
    Calculate game totals from RecentGames player data.
    Fallback if API is unavailable.
    """
    results = []

    # Get all player games from this date
    player_games = db.query(RecentGames).filter_by(game_date=game_date).all()

    if not player_games:
        return results

    # Group by game (using opponent team to identify unique games)
    games_by_teams = {}

    for pg in player_games:
        # Get player's team
        roster = db.query(TeamRoster).filter_by(player_id=pg.player_id).first()
        if not roster:
            continue

        # Create game key
        team_id = roster.team_id
        opp_id = pg.opponent_team_id
        game_key = tuple(sorted([team_id, opp_id]))

        if game_key not in games_by_teams:
            games_by_teams[game_key] = {
                'players': [],
                'team_ids': {team_id, opp_id}
            }

        games_by_teams[game_key]['players'].append({
            'player_id': pg.player_id,
            'team_id': team_id,
            'points': pg.points or 0
        })

    # Calculate totals for each game
    for game_key, game_data in games_by_teams.items():
        team_scores = {}
        for player in game_data['players']:
            tid = player['team_id']
            if tid not in team_scores:
                team_scores[tid] = 0
            team_scores[tid] += player['points']

        if len(team_scores) == 2:
            team_ids = list(team_scores.keys())
            # Determine home/away (simplified - would need game context)
            results.append({
                'team_ids': team_ids,
                'scores': team_scores,
                'total': sum(team_scores.values())
            })

    return results


def normalize_team_name(name: str) -> str:
    """Normalize team name for matching."""
    # Common variations
    name = name.lower().strip()

    mappings = {
        'la clippers': 'los angeles clippers',
        'la lakers': 'los angeles lakers',
        '76ers': 'philadelphia 76ers',
        'sixers': 'philadelphia 76ers',
        'blazers': 'portland trail blazers',
        'cavs': 'cleveland cavaliers',
        'wolves': 'minnesota timberwolves',
        'pels': 'new orleans pelicans',
    }

    for key, value in mappings.items():
        if key in name:
            return value

    return name


def match_projection_to_actual(projection: NBATotalsProjections, actuals: List[Dict]) -> Optional[Dict]:
    """
    Match a projection to actual game result.
    """
    proj_home = normalize_team_name(projection.home_team_name)
    proj_away = normalize_team_name(projection.away_team_name)

    for actual in actuals:
        actual_home = normalize_team_name(actual.get('home_team', ''))
        actual_away = normalize_team_name(actual.get('away_team', ''))

        # Check for match
        if (proj_home in actual_home or actual_home in proj_home) and \
           (proj_away in actual_away or actual_away in proj_away):
            return actual

    return None


def store_actual_result(projection: NBATotalsProjections, actual: Dict):
    """
    Store actual game result and calculate accuracy metrics.
    """
    try:
        # Check for existing actual
        existing = db.query(NBATotalsActuals).filter_by(
            game_date=projection.game_date,
            home_team_name=projection.home_team_name,
            away_team_name=projection.away_team_name
        ).first()

        actual_total = actual['total']
        projected_total = projection.projected_total
        market_total = projection.market_total

        # Calculate errors
        projection_error = actual_total - projected_total
        market_error = actual_total - market_total if market_total else None

        # Determine if over/under was correct
        was_over = actual_total > market_total if market_total else None

        # Did our prediction hit?
        correct_prediction = None
        if projection.recommendation and market_total:
            if projection.recommendation == 'OVER' and was_over:
                correct_prediction = True
            elif projection.recommendation == 'UNDER' and not was_over:
                correct_prediction = True
            elif projection.recommendation == 'NO_PLAY':
                correct_prediction = None  # Not applicable
            else:
                correct_prediction = False

        if existing:
            existing.actual_total = actual_total
            existing.home_actual_score = actual.get('home_score')
            existing.away_actual_score = actual.get('away_score')
            existing.projected_total = projected_total
            existing.market_total = market_total
            existing.projection_error = projection_error
            existing.market_error = market_error
            existing.was_over = was_over
            existing.correct_prediction = correct_prediction
        else:
            new_actual = NBATotalsActuals(
                game_date=projection.game_date,
                home_team_id=projection.home_team_id,
                away_team_id=projection.away_team_id,
                home_team_name=projection.home_team_name,
                away_team_name=projection.away_team_name,
                actual_total=actual_total,
                home_actual_score=actual.get('home_score'),
                away_actual_score=actual.get('away_score'),
                projected_total=projected_total,
                market_total=market_total,
                projection_error=projection_error,
                market_error=market_error,
                was_over=was_over,
                correct_prediction=correct_prediction
            )
            db.session.add(new_actual)

        db.session.commit()

        logger.info(
            f"Stored actual: {projection.away_team_name} @ {projection.home_team_name} "
            f"- Actual: {actual_total}, Projected: {projected_total:.1f}, "
            f"Error: {projection_error:+.1f}, Correct: {correct_prediction}"
        )

    except Exception as e:
        logger.error(f"Error storing actual result: {e}")
        db.session.rollback()


def calculate_accuracy_metrics(days: int = 30) -> Dict:
    """
    Calculate accuracy metrics over the specified period.
    """
    end_date = _today()
    start_date = end_date - timedelta(days=days)

    actuals = db.query(NBATotalsActuals).filter(
        NBATotalsActuals.game_date >= start_date,
        NBATotalsActuals.game_date <= end_date
    ).all()

    if not actuals:
        return {}

    # Calculate metrics
    total_games = len(actuals)
    projection_errors = [abs(a.projection_error) for a in actuals if a.projection_error is not None]

    # MAE
    mae = sum(projection_errors) / len(projection_errors) if projection_errors else None

    # RMSE
    rmse = None
    if projection_errors:
        rmse = (sum(e ** 2 for e in projection_errors) / len(projection_errors)) ** 0.5

    # Directional accuracy (for games with recommendations)
    games_with_rec = [a for a in actuals if a.correct_prediction is not None]
    correct_predictions = sum(1 for a in games_with_rec if a.correct_prediction)
    directional_accuracy = correct_predictions / len(games_with_rec) if games_with_rec else None

    # Over/under breakdown
    overs = [a for a in actuals if a.was_over is True]
    unders = [a for a in actuals if a.was_over is False]

    over_correct = sum(1 for a in overs if a.correct_prediction) if overs else 0
    under_correct = sum(1 for a in unders if a.correct_prediction) if unders else 0

    over_accuracy = over_correct / len(overs) if overs else None
    under_accuracy = under_correct / len(unders) if unders else None

    # Value plays (3+ point edge)
    projections = db.query(NBATotalsProjections).filter(
        NBATotalsProjections.game_date >= start_date,
        NBATotalsProjections.game_date <= end_date
    ).all()

    value_plays = [p for p in projections if p.edge and abs(p.edge) >= 3]
    value_actuals = []

    for vp in value_plays:
        actual = db.query(NBATotalsActuals).filter_by(
            game_date=vp.game_date,
            home_team_name=vp.home_team_name,
            away_team_name=vp.away_team_name
        ).first()
        if actual:
            value_actuals.append(actual)

    value_correct = sum(1 for a in value_actuals if a.correct_prediction)
    value_accuracy = value_correct / len(value_actuals) if value_actuals else None

    # Calculate ROI (assuming -110 odds)
    # Win = +90.91, Loss = -100
    wins = sum(1 for a in value_actuals if a.correct_prediction)
    losses = sum(1 for a in value_actuals if a.correct_prediction is False)
    roi = None
    if wins + losses > 0:
        profit = (wins * 90.91) - (losses * 100)
        roi = profit / ((wins + losses) * 100)

    # By edge size buckets
    def get_edge_bucket_stats(min_edge, max_edge):
        bucket_projs = [p for p in projections if p.edge and min_edge <= abs(p.edge) < max_edge]
        bucket_actuals = []
        for bp in bucket_projs:
            actual = db.query(NBATotalsActuals).filter_by(
                game_date=bp.game_date,
                home_team_name=bp.home_team_name,
                away_team_name=bp.away_team_name
            ).first()
            if actual:
                bucket_actuals.append(actual)
        correct = sum(1 for a in bucket_actuals if a.correct_prediction)
        acc = correct / len(bucket_actuals) if bucket_actuals else None
        return len(bucket_projs), acc

    edge_1_2_count, edge_1_2_acc = get_edge_bucket_stats(1, 2)
    edge_2_3_count, edge_2_3_acc = get_edge_bucket_stats(2, 3)
    edge_3_5_count, edge_3_5_acc = get_edge_bucket_stats(3, 5)
    edge_5_plus_count, edge_5_plus_acc = get_edge_bucket_stats(5, 100)

    metrics = {
        'date_range_start': start_date,
        'date_range_end': end_date,
        'total_games': total_games,
        'mean_absolute_error': round(mae, 2) if mae else None,
        'root_mean_square_error': round(rmse, 2) if rmse else None,
        'directional_accuracy': round(directional_accuracy, 3) if directional_accuracy else None,
        'over_accuracy': round(over_accuracy, 3) if over_accuracy else None,
        'under_accuracy': round(under_accuracy, 3) if under_accuracy else None,
        'value_plays_count': len(value_plays),
        'value_plays_accuracy': round(value_accuracy, 3) if value_accuracy else None,
        'value_plays_roi': round(roi, 3) if roi else None,
        'edge_1_2_count': edge_1_2_count,
        'edge_1_2_accuracy': round(edge_1_2_acc, 3) if edge_1_2_acc else None,
        'edge_2_3_count': edge_2_3_count,
        'edge_2_3_accuracy': round(edge_2_3_acc, 3) if edge_2_3_acc else None,
        'edge_3_5_count': edge_3_5_count,
        'edge_3_5_accuracy': round(edge_3_5_acc, 3) if edge_3_5_acc else None,
        'edge_5_plus_count': edge_5_plus_count,
        'edge_5_plus_accuracy': round(edge_5_plus_acc, 3) if edge_5_plus_acc else None,
    }

    return metrics


def save_accuracy_metrics(metrics: Dict):
    """Save accuracy metrics to database."""
    if not metrics:
        return

    try:
        # Check for existing record for this date range
        existing = db.query(NBATotalsAccuracy).filter_by(
            date_range_start=metrics['date_range_start'],
            date_range_end=metrics['date_range_end']
        ).first()

        if existing:
            for key, value in metrics.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
        else:
            new_record = NBATotalsAccuracy(
                date_range_start=metrics['date_range_start'],
                date_range_end=metrics['date_range_end'],
                total_games=metrics['total_games'],
                mean_absolute_error=metrics.get('mean_absolute_error'),
                root_mean_square_error=metrics.get('root_mean_square_error'),
                directional_accuracy=metrics.get('directional_accuracy'),
                over_accuracy=metrics.get('over_accuracy'),
                under_accuracy=metrics.get('under_accuracy'),
                value_plays_count=metrics.get('value_plays_count'),
                value_plays_accuracy=metrics.get('value_plays_accuracy'),
                value_plays_roi=metrics.get('value_plays_roi'),
                edge_1_2_count=metrics.get('edge_1_2_count'),
                edge_1_2_accuracy=metrics.get('edge_1_2_accuracy'),
                edge_2_3_count=metrics.get('edge_2_3_count'),
                edge_2_3_accuracy=metrics.get('edge_2_3_accuracy'),
                edge_3_5_count=metrics.get('edge_3_5_count'),
                edge_3_5_accuracy=metrics.get('edge_3_5_accuracy'),
                edge_5_plus_count=metrics.get('edge_5_plus_count'),
                edge_5_plus_accuracy=metrics.get('edge_5_plus_accuracy'),
            )
            db.session.add(new_record)

        db.session.commit()
        logger.info("Saved accuracy metrics to database")

    except Exception as e:
        logger.error(f"Error saving accuracy metrics: {e}")
        db.session.rollback()


def update_yesterdays_results():
    """
    Update actual results for yesterday's games.
    """
    yesterday = _today() - timedelta(days=1)

    logger.info(f"Updating results for {yesterday}")

    # Get projections for yesterday
    projections = db.query(NBATotalsProjections).filter_by(game_date=yesterday).all()

    if not projections:
        logger.info("No projections found for yesterday")
        return

    # Fetch actual scores
    actuals = fetch_game_scores_from_api(yesterday)

    if not actuals:
        logger.warning("Could not fetch game scores from API")
        return

    # Match and store results
    matched = 0
    for proj in projections:
        actual = match_projection_to_actual(proj, actuals)
        if actual:
            store_actual_result(proj, actual)
            matched += 1

    logger.info(f"Matched {matched}/{len(projections)} projections to actuals")


def print_accuracy_report(metrics: Dict):
    """Print accuracy report to console."""
    if not metrics:
        print("No accuracy data available")
        return

    print("\n" + "=" * 70)
    print("NBA TOTALS ACCURACY REPORT")
    print(f"Period: {metrics['date_range_start']} to {metrics['date_range_end']}")
    print("=" * 70)

    print(f"\nGames Tracked: {metrics['total_games']}")

    print("\nERROR METRICS:")
    print(f"  Mean Absolute Error: {metrics.get('mean_absolute_error', 'N/A')} points")
    print(f"  Root Mean Square Error: {metrics.get('root_mean_square_error', 'N/A')} points")

    print("\nDIRECTIONAL ACCURACY:")
    dir_acc = metrics.get('directional_accuracy')
    print(f"  Overall: {dir_acc * 100:.1f}%" if dir_acc else "  Overall: N/A")
    over_acc = metrics.get('over_accuracy')
    print(f"  Over Picks: {over_acc * 100:.1f}%" if over_acc else "  Over Picks: N/A")
    under_acc = metrics.get('under_accuracy')
    print(f"  Under Picks: {under_acc * 100:.1f}%" if under_acc else "  Under Picks: N/A")

    print("\nVALUE PLAYS (3+ point edge):")
    print(f"  Count: {metrics.get('value_plays_count', 0)}")
    val_acc = metrics.get('value_plays_accuracy')
    print(f"  Accuracy: {val_acc * 100:.1f}%" if val_acc else "  Accuracy: N/A")
    val_roi = metrics.get('value_plays_roi')
    print(f"  ROI: {val_roi * 100:.1f}%" if val_roi else "  ROI: N/A")

    print("\nPERFORMANCE BY EDGE SIZE:")
    print(f"  1-2 pts: {metrics.get('edge_1_2_count', 0)} games, {metrics.get('edge_1_2_accuracy', 0) * 100:.1f}% accuracy" if metrics.get('edge_1_2_accuracy') else f"  1-2 pts: {metrics.get('edge_1_2_count', 0)} games")
    print(f"  2-3 pts: {metrics.get('edge_2_3_count', 0)} games, {metrics.get('edge_2_3_accuracy', 0) * 100:.1f}% accuracy" if metrics.get('edge_2_3_accuracy') else f"  2-3 pts: {metrics.get('edge_2_3_count', 0)} games")
    print(f"  3-5 pts: {metrics.get('edge_3_5_count', 0)} games, {metrics.get('edge_3_5_accuracy', 0) * 100:.1f}% accuracy" if metrics.get('edge_3_5_accuracy') else f"  3-5 pts: {metrics.get('edge_3_5_count', 0)} games")
    print(f"  5+ pts:  {metrics.get('edge_5_plus_count', 0)} games, {metrics.get('edge_5_plus_accuracy', 0) * 100:.1f}% accuracy" if metrics.get('edge_5_plus_accuracy') else f"  5+ pts:  {metrics.get('edge_5_plus_count', 0)} games")

    print("\n" + "=" * 70)


def run_accuracy_tracker():
    """Main function to run accuracy tracking."""
    with app.app_context():
        db.create_all()

        # Update yesterday's results
        update_yesterdays_results()

        # Calculate and save metrics (30-day window)
        metrics = calculate_accuracy_metrics(days=30)
        if metrics:
            save_accuracy_metrics(metrics)
            print_accuracy_report(metrics)




def run(days: int = 30) -> dict:
    global db
    db = SessionLocal()
    try:
        update_yesterdays_results()
        metrics = calculate_accuracy_metrics(days=days)
        if metrics:
            save_accuracy_metrics(metrics)
        return {"status": "ok", "metrics": metrics or {}, "days": days}
    finally:
        db.close()
