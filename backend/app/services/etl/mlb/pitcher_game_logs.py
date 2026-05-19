import sys
import os
import requests
import pandas as pd

from app.models.predictions_models import HistoricalPitcherStats
import statsapi
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import inspect
from datetime import datetime


with app.app_context():
    inspector = inspect(db.engine)
    if not inspector.has_table(HistoricalPitcherStats.__tablename__):
        # db.engine.execute('DROP TABLE IF EXISTS historical_pitcher_stats')
        db.create_all()

def fetch_pitcher_game_logs(pitcher_id):
    url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}?hydrate=stats(group=[pitching],type=[gameLog],season=2025)"
    response = requests.get(url)
    data = response.json()
    if 'people' in data and len(data['people']) > 0 and 'stats' in data['people'][0]:
        stats = data['people'][0]['stats']
        game_logs = next((stat['splits'] for stat in stats if stat['type']['displayName'] == 'gameLog' and stat['group']['displayName'] == 'pitching'), [])
        if game_logs:
            print("GAME LOGS: ", game_logs)
            return game_logs
        else:
            print("No game logs found for this pitcher.")
            return []
    else:
        print("No stats found for this pitcher.")
        return []

def safe_divide(numerator, denominator):
    return numerator / denominator if denominator != 0 else 0

def calculate_metrics(game_logs, game_date):
    relevant_logs = [log for log in game_logs if log['date'] == game_date]
    if not relevant_logs:
        print("No Data Found for  matching Date: "  ,game_date)
        return None, None, None, None, None  # Return None for all fields if no relevant logs are found

    log = relevant_logs[0]
    innings_pitched = float(log['stat'].get('inningsPitched', 0))
    strikeouts = log['stat'].get('strikeOuts', 0)
    at_bats = log['stat'].get('atBats', 0)
    walks = log['stat'].get('baseOnBalls', 0)
    hits = log['stat'].get('hits', 0)
    return innings_pitched, strikeouts, at_bats, walks, hits

def calculate_metrics_actuals_v_projections(game_logs, game_date):
    # Convert log dates to datetime objects for comparison
    for log in game_logs:
        log['date'] = datetime.strptime(log['date'], '%Y-%m-%d').date()

    relevant_logs = [log for log in game_logs if log['date'] == game_date]
    if not relevant_logs:
        print("No Data Found for  matching Date: ", game_date)
        return None, None, None, None, None  # Return None for all fields if no relevant logs are found

    log = relevant_logs[0]
    innings_pitched = float(log['stat'].get('inningsPitched', 0))
    strikeouts = log['stat'].get('strikeOuts', 0)
    at_bats = log['stat'].get('atBats', 0)
    walks = log['stat'].get('baseOnBalls', 0)
    hits = log['stat'].get('hits', 0)
    return innings_pitched, strikeouts, at_bats, walks, hits

def get_todays_games():
    today = datetime.today().date().strftime('%Y-%m-%d')
    schedule = statsapi.schedule(date=today)
    return schedule

def fetch_todays_pitchers():
    schedule = get_todays_games()
    pitchers = []

    for game in schedule:
        for team in ['home', 'away']:
            probable_pitcher_key = f'{team}_probable_pitcher'
            if probable_pitcher_key in game:
                pitcher_name = game[probable_pitcher_key]
                team_name_key = f'{team}_name'
                opponent_team = 'away' if team == 'home' else 'home'
                opponent_team_id = game[f'{opponent_team}_id']
                pitcher_id = None
                game_date = game['game_date']

                try:
                    pitcher_id = statsapi.lookup_player(pitcher_name)[0]['id']
                except IndexError:
                    print(f"Error finding pitcher ID for {pitcher_name}")
                    continue

                pitcher_stats_data = statsapi.player_stat_data(pitcher_id, group="pitching", type="career", sportId=1)
                try:
                    pitch_hand = pitcher_stats_data.get('pitch_hand', {})
                except KeyError:
                    print(f"Error extracting pitch hand for {pitcher_name}")
                    pitch_hand = 'Unknown'

                pitchers.append({
                    'name': pitcher_name,
                    'pitcher_id': pitcher_id,
                    'pitch_hand': pitch_hand,
                    'team': game[team_name_key],
                    'opponent': game[f'{opponent_team}_name'],
                    'game_date': game_date
                })
    return pitchers

def fetch_days_pitchers(date):
    schedule = statsapi.schedule(date)
    pitchers = []

    for game in schedule:
        for team in ['home', 'away']:
            probable_pitcher_key = f'{team}_probable_pitcher'
            if probable_pitcher_key in game:
                pitcher_name = game[probable_pitcher_key]
                team_name_key = f'{team}_name'
                opponent_team = 'away' if team == 'home' else 'home'
                opponent_team_id = game[f'{opponent_team}_id']
                pitcher_id = None
                game_date = game['game_date']

                try:
                    pitcher_id = statsapi.lookup_player(pitcher_name)[0]['id']
                except IndexError:
                    print(f"Error finding pitcher ID for {pitcher_name}")
                    continue

                pitcher_stats_data = statsapi.player_stat_data(pitcher_id, group="pitching", type="season")
                try:
                    pitch_hand = pitcher_stats_data.get('pitch_hand', {})
                except KeyError:
                    print(f"Error extracting pitch hand for {pitcher_name}")
                    pitch_hand = 'Unknown'

                pitchers.append({
                    'name': pitcher_name,
                    'pitcher_id': pitcher_id,
                    'pitch_hand': pitch_hand,
                    'team': game[team_name_key],
                    'opponent': game[f'{opponent_team}_name'],
                    'game_date': game_date
                })
    return pitchers

def main():
    with app.app_context():
        try:
            pitchers = fetch_todays_pitchers()
            season = 2025
            for pitcher in pitchers:
                pitcher_id = pitcher['pitcher_id']
                game_logs = fetch_pitcher_game_logs(pitcher_id)
                for game_log in game_logs:
                    try:
                        stat = game_log['stat']
                        date = game_log['date']
                        opponent = game_log['team']['name']

                        # Fetch all metrics including walks and hits
                        innings_pitched, strikeouts, at_bats, walks, hits = calculate_metrics(game_logs, date)

                        # Ensure walks is not None
                        walks = walks if walks is not None else 0

                        # Calculate WHIP
                        whip = safe_divide(walks + hits, innings_pitched)

                        # Check if the record already exists before inserting
                        existing_entry = HistoricalPitcherStats.query.filter_by(
                            player_id=pitcher_id, date=date
                        ).first()

                        if existing_entry:
                            print(f"Skipping duplicate record for {pitcher['name']} on {date}")
                            continue

                        # Create new entry
                        new_stat = HistoricalPitcherStats(
                            player_id=pitcher_id,
                            name=pitcher['name'],
                            pitch_hand=pitcher['pitch_hand'],
                            season=season,
                            date=date,
                            strikeouts=strikeouts,
                            innings_pitched=innings_pitched,
                            opponent_team=opponent,
                            at_bats=at_bats,
                            walks=walks,
                            hits=hits,
                            baseOnBalls=walks,  # Assuming baseOnBalls is the same as walks
                            whip=whip,
                            numberOfPitches=stat.get('numberOfPitches', 0)
                        )

                        db.session.add(new_stat)
                        db.session.commit()
                        print(f"Inserted new record for {pitcher['name']} on {date}")

                    except SQLAlchemyError as e:
                        print(f"Database error while inserting data for pitcher {pitcher['name']} on date {date}: {e}")
                        db.session.rollback()
                    except KeyError as e:
                        print(f"Missing key in game log for pitcher {pitcher['name']} on date {date}: {e}")

            print("Data successfully stored!")
        except SQLAlchemyError as e:
            print(f"Database error: {e}")
            db.session.rollback()
        except Exception as e:
            print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
