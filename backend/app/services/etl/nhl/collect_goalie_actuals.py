from app.services.etl.nhl._db import db_session
#!/usr/bin/env python3
"""
NHL Goalie Actuals Collection Script
Collects actual goalie save performance data and compares with predictions
"""

from datetime import datetime, date, timedelta
import requests

# Add parent directories to path

from app.models.predictions_models import NHLGoaliePredictions, NHLGoalieActuals
from sqlalchemy import and_

def get_yesterday_games():
    """Get completed games from yesterday"""
    yesterday = date.today() - timedelta(days=1)

    # NHL API endpoint for schedule
    url = f"https://api-web.nhle.com/v1/schedule/{yesterday.strftime('%Y-%m-%d')}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        games = []
        if 'gameWeek' in data:
            for game_day in data['gameWeek']:
                if 'games' in game_day:
                    for game in game_day['games']:
                        if game.get('gameState') in ['OFF', 'FINAL']:  # Completed games
                            games.append(game)

        print(f"Found {len(games)} completed games from {yesterday}")
        return games, yesterday

    except Exception as e:
        print(f"Error fetching yesterday's games: {e}")
        return [], yesterday

def get_game_stats(game_id):
    """Get detailed stats for a specific game"""
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"

    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching game {game_id} stats: {e}")
        return None

def extract_goalie_stats(game_data, game_id, game_date):
    """Extract goalie statistics from game data"""
    goalie_stats = []

    if not game_data or 'playerByGameStats' not in game_data:
        return goalie_stats

    # Get team data
    away_team = game_data.get('awayTeam', {})
    home_team = game_data.get('homeTeam', {})

    # Process away team goalies
    if 'awayTeam' in game_data['playerByGameStats']:
        for position, players in game_data['playerByGameStats']['awayTeam'].items():
            if position == 'goalies':
                for goalie in players:
                    stats = {
                        'game_id': game_id,
                        'game_date': game_date,
                        'goalie_id': goalie.get('playerId'),
                        'goalie_name': f"{goalie.get('name', {}).get('default', '')}",
                        'team_name': away_team.get('name', {}).get('default', ''),
                        'opponent_team_name': home_team.get('name', {}).get('default', ''),
                        'actual_saves': goalie.get('saves', 0),
                        'actual_shots_against': goalie.get('shotsAgainst', 0),
                        'actual_save_pct': goalie.get('savePctg', 0.0),
                        'actual_goals_against': goalie.get('goalsAgainst', 0),
                        'actual_toi': goalie.get('toi', '0:00'),
                        'decision': goalie.get('decision', '')
                    }
                    goalie_stats.append(stats)

    # Process home team goalies
    if 'homeTeam' in game_data['playerByGameStats']:
        for position, players in game_data['playerByGameStats']['homeTeam'].items():
            if position == 'goalies':
                for goalie in players:
                    stats = {
                        'game_id': game_id,
                        'game_date': game_date,
                        'goalie_id': goalie.get('playerId'),
                        'goalie_name': f"{goalie.get('name', {}).get('default', '')}",
                        'team_name': home_team.get('name', {}).get('default', ''),
                        'opponent_team_name': away_team.get('name', {}).get('default', ''),
                        'actual_saves': goalie.get('saves', 0),
                        'actual_shots_against': goalie.get('shotsAgainst', 0),
                        'actual_save_pct': goalie.get('savePctg', 0.0),
                        'actual_goals_against': goalie.get('goalsAgainst', 0),
                        'actual_toi': goalie.get('toi', '0:00'),
                        'decision': goalie.get('decision', '')
                    }
                    goalie_stats.append(stats)

    return goalie_stats

def match_with_predictions(goalie_stats):
    """Match actual results with our predictions"""
    results_processed = 0

    for stats in goalie_stats:
        goalie_name = stats['goalie_name']
        game_date = stats['game_date']
        goalie_id = stats['goalie_id']

        # Only process goalies who played significant time (> 10 minutes)
        toi_parts = stats['actual_toi'].split(':')
        if len(toi_parts) == 2:
            minutes = int(toi_parts[0])
            if minutes < 10:
                print(f"⏭️  Skipping {goalie_name} - only played {stats['actual_toi']}")
                continue

        # Check if we already have this result
        existing = db_session.query(NHLGoalieActuals).filter(
            and_(
                NHLGoalieActuals.game_id == stats['game_id'],
                NHLGoalieActuals.goalie_id == goalie_id
            )
        ).first()

        if existing:
            print(f"⏭️  Result already exists for {goalie_name} on {game_date}")
            continue

        # Find matching prediction
        prediction = db_session.query(NHLGoaliePredictions).filter(
            and_(
                NHLGoaliePredictions.goalie_name == goalie_name,
                NHLGoaliePredictions.game_date == game_date
            )
        ).first()

        # Prepare actual result data
        actual_data = {
            'game_id': stats['game_id'],
            'game_date': game_date,
            'goalie_id': goalie_id,
            'goalie_name': goalie_name,
            'team_name': stats['team_name'],
            'opponent_team_name': stats['opponent_team_name'],
            'actual_saves': stats['actual_saves'],
            'actual_shots_against': stats['actual_shots_against'],
            'actual_save_pct': stats['actual_save_pct'],
            'actual_goals_against': stats['actual_goals_against'],
            'actual_toi': stats['actual_toi'],
            'decision': stats['decision']
        }

        if prediction:
            # Add prediction comparison data
            predicted_saves = prediction.predicted_saves
            actual_saves = stats['actual_saves']

            actual_data['predicted_saves'] = predicted_saves
            actual_data['predicted_shots_against'] = prediction.predicted_shots_against
            actual_data['prediction_error'] = abs(predicted_saves - actual_saves)

            # Check if prediction was correct (within 2 saves is considered accurate)
            actual_data['correct_prediction'] = abs(predicted_saves - actual_saves) <= 2

            # Add sportsbook line and recommendation tracking
            if prediction.saves_line:
                actual_data['sportsbook'] = prediction.sportsbook
                actual_data['saves_line'] = prediction.saves_line
                actual_data['over_odds'] = prediction.over_odds
                actual_data['under_odds'] = prediction.under_odds
                actual_data['betting_recommendation'] = prediction.betting_recommendation
                actual_data['edge_category'] = prediction.edge_category
                actual_data['edge_saves'] = prediction.edge_saves

                # Determine if recommendation was correct
                if prediction.betting_recommendation and prediction.betting_recommendation != 'PASS':
                    line = prediction.saves_line
                    if 'OVER' in prediction.betting_recommendation:
                        # We recommended OVER, check if it hit
                        actual_data['recommendation_correct'] = actual_saves > line
                    elif 'UNDER' in prediction.betting_recommendation:
                        # We recommended UNDER, check if it hit
                        actual_data['recommendation_correct'] = actual_saves < line

            print(f"✅ {goalie_name}: {actual_saves} saves (predicted {predicted_saves:.1f})")
            if actual_data.get('betting_recommendation'):
                rec_result = "✅" if actual_data.get('recommendation_correct') else "❌"
                print(f"   Recommendation: {prediction.betting_recommendation} ({prediction.edge_category}) {rec_result}")
        else:
            print(f"⚠️  No prediction found for {goalie_name} on {game_date}")
            print(f"   Actual: {actual_saves} saves")

        # Create actual result record
        goalie_actual = NHLGoalieActuals(**actual_data)
        db_session.add(goalie_actual)
        results_processed += 1

    db_session.commit()
    print(f"\n📊 Processed {results_processed} goalie results")

    # Print summary stats
    if results_processed > 0:
        print("\n📈 Summary Statistics:")

        # Overall prediction accuracy
        all_results = db_session.query(NHLGoalieActuals).filter(
            NHLGoalieActuals.predicted_saves.isnot(None)
        ).all()

        if all_results:
            correct = sum(1 for r in all_results if r.correct_prediction)
            total = len(all_results)
            accuracy = (correct / total * 100) if total > 0 else 0
            print(f"  Overall Prediction Accuracy: {correct}/{total} ({accuracy:.1f}%)")

        # Recommendation success rate
        rec_results = db_session.query(NHLGoalieActuals).filter(
            and_(
                NHLGoalieActuals.recommendation_correct.isnot(None),
                NHLGoalieActuals.betting_recommendation != 'PASS'
            )
        ).all()

        if rec_results:
            correct_recs = sum(1 for r in rec_results if r.recommendation_correct)
            total_recs = len(rec_results)
            rec_accuracy = (correct_recs / total_recs * 100) if total_recs > 0 else 0
            print(f"  Recommendation Success Rate: {correct_recs}/{total_recs} ({rec_accuracy:.1f}%)")

            # Break down by edge category
            for edge in ['HIGH', 'MEDIUM', 'LOW']:
                edge_results = [r for r in rec_results if r.edge_category == edge]
                if edge_results:
                    edge_correct = sum(1 for r in edge_results if r.recommendation_correct)
                    edge_total = len(edge_results)
                    edge_pct = (edge_correct / edge_total * 100) if edge_total > 0 else 0
                    print(f"    {edge} Edge: {edge_correct}/{edge_total} ({edge_pct:.1f}%)")

def update_goalie_actuals(target_date=None):
    """
    Main function to update goalie actuals

    Args:
        target_date (date): Specific date to process, defaults to yesterday
    """
    print("🏒 NHL Goalie Actuals Collection")
    print("=" * 50)

    if target_date:
        # Use specific date
        yesterday = target_date
        # Fetch games for that date
        url = f"https://api-web.nhle.com/v1/schedule/{yesterday.strftime('%Y-%m-%d')}"
        response = requests.get(url)
        data = response.json()

        games = []
        if 'gameWeek' in data:
            for game_day in data['gameWeek']:
                if 'games' in game_day:
                    for game in game_day['games']:
                        if game.get('gameState') in ['OFF', 'FINAL']:
                            games.append(game)
    else:
        # Use yesterday's games
        games, yesterday = get_yesterday_games()

    if not games:
        print(f"No completed games found for {yesterday}")
        return

    all_goalie_stats = []

    for game in games:
        game_id = game['id']
        print(f"\nProcessing game {game_id}...")

        game_data = get_game_stats(game_id)
        if game_data:
            goalie_stats = extract_goalie_stats(game_data, game_id, yesterday)
            all_goalie_stats.extend(goalie_stats)

    print(f"\nFound stats for {len(all_goalie_stats)} goalies")

    if all_goalie_stats:
        match_with_predictions(all_goalie_stats)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Collect NHL goalie actual results')
    parser.add_argument('--date', type=str, help='Date to process (YYYY-MM-DD), defaults to yesterday')

    args = parser.parse_args()

    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        update_goalie_actuals(target_date)
    else:
        update_goalie_actuals()


def run() -> dict:
    from app.services.etl.nhl._db import close_session, init_session
    init_session()
    try:
        update_goalie_actuals()
        return {"status": "ok", "task": "nhl_collect_goalie_actuals"}
    finally:
        close_session()
