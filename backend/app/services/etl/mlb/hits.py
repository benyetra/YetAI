from datetime import date as date_type, datetime, timedelta
import sys
import os
import statsapi
import requests
from app.services.etl.mlb._db import db_session
from app.services.etl.mlb._mlb_utils import *
from app.models.predictions_models import BlowoutChances, Hitter, Homer

from app.services.etl.mlb.strikeouts import fetch_pitcher_data
from sqlalchemy import text


def get_todays_games():
    today = datetime.today().date().strftime('%Y-%m-%d')
    schedule = statsapi.schedule(date=today)
    return schedule

def _parse_game_date(value) -> date_type:
    if isinstance(value, date_type):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def get_game_log_date(player_id, date):
    # Use 'MM/DD/YYYY' format for API requests
    date_obj = _parse_game_date(date)
    start_date = date_obj.strftime('%m/%d/%Y')
    end_date = date_obj.strftime('%m/%d/%Y')
    hydrate = f"stats(group=[hitting],type=[gameLog],startDate={start_date},endDate={end_date})"
    
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}"
    params = {'hydrate': hydrate}
    response = requests.get(url, params=params)
    data = response.json()
    
    game_logs = []

    if 'people' in data and isinstance(data['people'], list) and len(data['people']) > 0:
        person = data['people'][0]
        if 'stats' in person and isinstance(person['stats'], list) and len(person['stats']) > 0:
            stats = person['stats'][0]['splits']
            if isinstance(stats, list):
                for split in stats:
                    if 'stat' in split:
                        stat = split['stat']
                        game_date = split.get('date', '')

                        game_log = {
                            'game_date': game_date,
                            'hits': int(stat.get('hits', 0)),
                            'plateAppearances': int(stat.get('plateAppearances', 0)),
                            'avg': float(stat.get('avg', 0)),
                            'flyOuts': int(stat.get('flyOuts', 0)),
                            'groundOuts': int(stat.get('groundOuts', 0)),
                            'homeRuns': int(stat.get('homeRuns', 0))
                        }
                        game_logs.append(game_log)

    game_logs.sort(key=lambda x: datetime.strptime(x['game_date'], '%Y-%m-%d'), reverse=True)
    return game_logs

def calculate_metrics_actuals_v_projections(game_logs, game_date):
    game_date = _parse_game_date(game_date)
    for log in game_logs:
        log_date = datetime.strptime(log['game_date'], '%Y-%m-%d').date()
        if log_date == game_date:
            hits = log.get('hits', 0)
            home_runs = log.get('homeRuns', 0)
            return hits, home_runs
    print(f"No data found for matching date: {game_date}")
    return None, None

def fetch_days_hitters(date):
    schedule = statsapi.schedule(date)
    hitters = []
    for game in schedule:
        game_id = game['game_id']
        batters = get_starting_batters(game_id)
        hitters.extend(batters)
    return hitters

def get_starting_batters(game_id):
    game_data = statsapi.get("game", {"gamePk": game_id})
    batters = []
    batting_orders = {}

    if 'liveData' in game_data and 'boxscore' in game_data['liveData']:
        boxscore = game_data['liveData']['boxscore']
        teams = ['home', 'away']
        
        for team in teams:
            for player_id_str, player_info in boxscore['teams'][team]['players'].items():
                player_id = int(player_id_str.replace('ID', ''))
                if 'battingOrder' in player_info:
                    batting_order = int(player_info['battingOrder'])
                    batting_orders[player_id] = batting_order
                player = statsapi.lookup_player(player_id)
                if player:
                    player[0]['battingOrder'] = batting_orders.get(player_id)
                    batters.append(player[0])

    return batters

def get_game_logs(player_id):
    end_date = datetime.today()
    start_date = end_date - timedelta(days=30)

    def _fetch_logs(start, end):
        hydrate = f"stats(group=[hitting],type=[gameLog],startDate={start.strftime('%Y-%m-%d')},endDate={end.strftime('%Y-%m-%d')})"
        url = f"https://statsapi.mlb.com/api/v1/people/{player_id}"
        params = {'hydrate': hydrate}
        response = requests.get(url, params=params)
        data = response.json()
        logs = []
        if 'people' in data and isinstance(data['people'], list) and len(data['people']) > 0:
            person = data['people'][0]
            if 'stats' in person and isinstance(person['stats'], list) and len(person['stats']) > 0:
                stats = person['stats'][0]['splits']
                if isinstance(stats, list):
                    for split in stats:
                        if 'stat' in split:
                            stat = split['stat']
                            game_date = split.get('date', '')
                            logs.append({
                                'game_date': game_date,
                                'hits': int(stat.get('hits', 0)),
                                'plateAppearances': int(stat.get('plateAppearances', 0)),
                                'avg': float(stat.get('avg', 0)),
                                'flyOuts': int(stat.get('flyOuts', 0)),
                                'groundOuts': int(stat.get('groundOuts', 0)),
                                'homeRuns': int(stat.get('homeRuns', 0))
                            })
        return logs

    game_logs = _fetch_logs(start_date, end_date)

    # Early season fallback: if no games in last 30 days, look back into prior season
    if not game_logs:
        game_logs = _fetch_logs(end_date - timedelta(days=365), end_date)

    game_logs.sort(key=lambda x: datetime.strptime(x['game_date'], '%Y-%m-%d'), reverse=True)
    return game_logs[:15]

def get_career_batting_average_against_pitcher(player_id, opponent_id):
    hydrate = 'stats(group=[hitting],type=[vsPlayer],opposingPlayerId={})'.format(opponent_id)
    url = f'https://statsapi.mlb.com/api/v1/people/{player_id}?hydrate={hydrate}'
    
    response = requests.get(url)
    data = response.json()
    
    try:
        if 'people' in data and data['people']:
            splits = data['people'][0].get('stats', [{}])[0].get('splits', [])
            if splits:
                batting_average = float(splits[0]['stat'].get('avg', 0.0))
                at_bats = splits[0]['stat'].get('atBats', 0)
                hits = splits[0]['stat'].get('hits', 0)
                return batting_average, at_bats, hits
        return None, 0, 0
    except (KeyError, IndexError):
        return None, 0, 0

def calculate_batting_average(player_id, pitch_hand):
    sit_code = "vr" if pitch_hand == "R" else "vl"
    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}"

    # Try current season splits first
    params = {'hydrate': f"stats(group=[hitting],type=[statSplits],sitCodes={sit_code})"}
    response = requests.get(url, params=params)
    data = response.json()

    if 'people' in data and isinstance(data['people'], list) and len(data['people']) > 0:
        person = data['people'][0]
        if 'stats' in person and isinstance(person['stats'], list) and len(person['stats']) > 0:
            stats = person['stats'][0]['splits']
            if isinstance(stats, list):
                for split in stats:
                    if 'stat' in split and 'avg' in split['stat']:
                        avg = float(split['stat']['avg'])
                        if avg > 0:
                            return avg

    # Early season fallback: use career splits vs handedness
    params_career = {'hydrate': f"stats(group=[hitting],type=[career],sitCodes={sit_code})"}
    response_career = requests.get(url, params=params_career)
    data_career = response_career.json()

    if 'people' in data_career and isinstance(data_career['people'], list) and len(data_career['people']) > 0:
        person = data_career['people'][0]
        if 'stats' in person and isinstance(person['stats'], list) and len(person['stats']) > 0:
            stats = person['stats'][0]['splits']
            if isinstance(stats, list):
                for split in stats:
                    if 'stat' in split and 'avg' in split['stat']:
                        avg = float(split['stat']['avg'])
                        if avg > 0:
                            return avg

    print(f"Error fetching batting average for player {player_id} against {pitch_hand} hand")
    return 0.0

def fetch_hitters_data():
    schedule = get_todays_games()
    hitters = []
    for game in schedule:
        venue_name = game['venue_name']
        game_id = game['game_id']
        home_team_name = game['home_name']
        away_team_name = game['away_name']
        home_probable_pitcher = game['home_probable_pitcher']
        away_probable_pitcher = game['away_probable_pitcher']
        game_time = game['game_datetime']
        try:
            game_time = datetime.strptime(game_time, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            game_time = None
        starting_batters = get_starting_batters(game_id)

        for batter in starting_batters:
            player_id = batter['id']
            player_name = batter['fullName']
            batter_team_id = batter['currentTeam']['id']
            batting_order_position = batter.get('battingOrder', None)

            if batter_team_id == game['home_id']:
                opponent_pitcher = away_probable_pitcher
                opponent_team_name = away_team_name
            else:
                opponent_pitcher = home_probable_pitcher
                opponent_team_name = home_team_name  

            try:
                pitcher = statsapi.lookup_player(opponent_pitcher)
                pitcher_id = pitcher[0]['id'] if pitcher else None
            except IndexError:
                print(f"Error finding pitcher ID for {opponent_pitcher}")
                continue

            if not pitcher_id:
                print(f"Pitcher ID not found for {opponent_pitcher}")
                continue

            pitcher_stats_data = statsapi.player_stat_data(pitcher_id, group="pitching", type="season")
            try:
                pitch_hand = pitcher_stats_data['pitch_hand']
            except KeyError:
                print(f"Error extracting pitch hand for {opponent_pitcher}")
                pitch_hand = 'Unknown'
            opponent_pitcher_hand = pitch_hand
            game_logs = get_game_logs(player_id)

            # Detect early season: no game logs from the current year
            current_year = str(datetime.today().year)
            early_season = not game_logs or not any(
                log['game_date'].startswith(current_year) for log in game_logs
            )

            hits_in_last_10_games = sum(1 for log in game_logs if log['hits'] > 0)
            home_runs_in_last_10_games = sum(log.get('homeRuns', 0) for log in game_logs)
            season_avg_vs_handed = calculate_batting_average(player_id, opponent_pitcher_hand)
                
            batting_average_vs_pitcher, at_bats_vs_pitcher, hits_vs_pitcher = get_career_batting_average_against_pitcher(player_id, pitcher_id)

            if batting_average_vs_pitcher is not None:
                print(f"The career batting average against pitcher {pitcher_id} is: {batting_average_vs_pitcher:.3f}")
            else:
                print("No data available for the specified player and opponent.")

            def get_combined_score(
                hits_in_last_10_games,
                season_avg_vs_handed,
                batting_average_vs_pitcher,
                at_bats_vs_pitcher,
                home_runs_last_10_games,
                batting_order_position,
                early_season=False
            ):
                # Early season: relaxed gates (using prior season / career data)
                min_hits = 4 if early_season else 7
                min_avg = 0.220 if early_season else 0.275

                # Check if the conditions for scoring are met
                if (
                    hits_in_last_10_games < min_hits or
                    batting_average_vs_pitcher is None or
                    batting_average_vs_pitcher <= min_avg or
                    season_avg_vs_handed is None or
                    season_avg_vs_handed <= min_avg
                ):
                    return 0.0  # Return a score of 0 if conditions are not met

                # Assigning weights to each factor
                weights = {
                    'recent_hits_weight': 0.35,  # Slightly reduced to balance other factors
                    'season_avg_weight': 0.25,   # Reduced to not overly emphasize the season average
                    'vs_pitcher_weight': 0.45,   # Still high due to its direct matchup relevance
                    'batting_order_weight': 1.0 if batting_order_position and int(batting_order_position / 100) <= 3 else 0.5,  # Boosted for top 3 order positions
                    'at_bats_vs_pitcher_weight': 0.2,  # Adjusted to reflect the importance of sample size without overpowering other stats
                    'home_runs_weight': 0.15    # Increased slightly to account for power as an influence on overall hitting potential
                }

                # Calculate factors
                recent_hits_factor = hits_in_last_10_games * weights['recent_hits_weight']
                season_avg_factor = (season_avg_vs_handed or 0) * weights['season_avg_weight']
                vs_pitcher_factor = (batting_average_vs_pitcher or 0) * weights['vs_pitcher_weight']
                at_bats_vs_pitcher_factor = (at_bats_vs_pitcher or 0) * weights['at_bats_vs_pitcher_weight']
                home_runs_factor = home_runs_last_10_games * weights['home_runs_weight']

                # Combine all factors into the score
                combined_score = (
                    recent_hits_factor
                    + season_avg_factor
                    + vs_pitcher_factor
                    + at_bats_vs_pitcher_factor
                    + home_runs_factor
                ) * weights['batting_order_weight']

                # Round the combined score to two decimal places
                return round(combined_score, 2)


            def get_homer_score(
                hits_in_last_10_games,
                season_avg_vs_handed,
                batting_average_vs_pitcher,
                homers_in_last_10_games,
                at_bats_vs_pitcher,
                batting_order_position,
                early_season=False
            ):
                # Early season: relaxed gates (using prior season / career data)
                min_homers = 1 if early_season else 2
                min_hits = 4 if early_season else 7
                min_avg = 0.220 if early_season else 0.275

                # Check if the conditions for scoring are met
                if (
                    homers_in_last_10_games < min_homers or
                    hits_in_last_10_games < min_hits or
                    batting_average_vs_pitcher is None or
                    batting_average_vs_pitcher <= min_avg or
                    season_avg_vs_handed is None or
                    season_avg_vs_handed <= min_avg
                ):
                    return 0.0  # Return a score of 0 if conditions are not met

                # Assigning weights to each factor
                weights = {
                    'recent_hits_weight': 0.25,  # Weight for recent hits, less critical for HR prediction
                    'season_avg_weight': 0.2,    # Season average vs handed pitcher, moderate relevance
                    'vs_pitcher_weight': 0.4,    # Weight for performance vs specific pitcher
                    'home_runs_recent_weight': 0.6,  # Higher weight due to recent HRs being directly relevant
                    'at_bats_vs_pitcher_weight': 0.1,  # Consider sample size against the pitcher
                    'batting_order_weight': 1.2 if batting_order_position and int(batting_order_position / 100) <= 3 else 0.8,  # Boost for top 3 positions
                }

                # Calculate factors
                recent_hits_factor = hits_in_last_10_games * weights['recent_hits_weight']
                season_avg_factor = (season_avg_vs_handed or 0) * weights['season_avg_weight']
                vs_pitcher_factor = (batting_average_vs_pitcher or 0) * weights['vs_pitcher_weight']
                home_runs_factor = homers_in_last_10_games * weights['home_runs_recent_weight']
                at_bats_vs_pitcher_factor = (at_bats_vs_pitcher or 0) * weights['at_bats_vs_pitcher_weight']

                # Combine all factors into the homer score
                homer_score = (
                    recent_hits_factor
                    + season_avg_factor
                    + vs_pitcher_factor
                    + home_runs_factor
                    + at_bats_vs_pitcher_factor
                ) * weights['batting_order_weight']

                # Round the homer score to two decimal places
                return round(homer_score, 2)


            combined_score = get_combined_score(hits_in_last_10_games, season_avg_vs_handed, batting_average_vs_pitcher, at_bats_vs_pitcher, home_runs_in_last_10_games, batting_order_position, early_season)
            homer_score = get_homer_score(hits_in_last_10_games, season_avg_vs_handed, batting_average_vs_pitcher, home_runs_in_last_10_games, at_bats_vs_pitcher, batting_order_position, early_season)

            hitter_data = {
                'player_id': player_id,
                'player_name': player_name,
                'team': home_team_name if batter_team_id == game['home_id'] else away_team_name,
                'opponent': opponent_team_name,
                'opponent_pitcher': opponent_pitcher,
                'opponent_pitcher_hand': opponent_pitcher_hand,
                'game_time': game_time,
                'hits_last_10_games': hits_in_last_10_games,
                'home_runs_last_10_games': home_runs_in_last_10_games,
                'season_avg_vs_handed': season_avg_vs_handed,
                'batting_average_vs_pitcher': batting_average_vs_pitcher,
                'hits_vs_pitcher': hits_vs_pitcher,
                'at_bats_vs_pitcher': at_bats_vs_pitcher,
                'combined_score': combined_score,
                'homer_score': homer_score,
                'venue_name': venue_name,
                'batting_order_position': batting_order_position,
                'game_id': game_id
            }
            hitters.append(hitter_data)

    unique_hitters_dict = { (hitter['player_id'], hitter['opponent_pitcher']): hitter for hitter in hitters }
    unique_hitters = list(unique_hitters_dict.values())
    unique_hitters.sort(key=lambda x: x['combined_score'], reverse=True)
    print(f"Unique hitters: {len(unique_hitters)}")
    
    home_runs = [hitter for hitter in unique_hitters if hitter['home_runs_last_10_games'] > 0]
    home_runs.sort(key=lambda x: x['homer_score'], reverse=True)  
    print(f"Home runs: {len(home_runs)}")
    
    return unique_hitters, home_runs

def filter_hitters(hitters, min_combined_score=None):
    if min_combined_score is None:
        min_combined_score = 2
    filtered_hitters = [
        hitter
        for hitter in hitters
        if hitter["combined_score"] is not None
        and hitter["combined_score"] >= min_combined_score
    ]
    print(
        f"Filtered {len(hitters)} to {len(filtered_hitters)} hitters "
        f"with combined score >= {min_combined_score}."
    )
    return filtered_hitters


def filter_homers(hitters, min_combined_score=4):
    filtered_homers = [
        hitter for hitter in hitters 
        if hitter['homer_score'] is not None and hitter['homer_score'] >= min_combined_score
    ]
    print(f"Filtered {len(hitters)} to {len(filtered_homers)} hitters with a homer score of {min_combined_score} or more.")
    return filtered_homers

def store_hitters_data(hitters):
    stored_hitters = []
    
    if not hitters:
        print("No hitters data to process.")
        return stored_hitters

    for index, hitter_data in enumerate(hitters):
        try:
            required_keys = ['player_id', 'player_name', 'team', 'opponent', 'opponent_pitcher', 'opponent_pitcher_hand', 'game_time', 'hits_last_10_games', 'season_avg_vs_handed', 'batting_average_vs_pitcher', 'combined_score', 'venue_name', 'game_id']
            for key in required_keys:
                if key not in hitter_data:
                    raise ValueError(f"Missing required key '{key}' in hitter data: {hitter_data}")

            game_time = hitter_data['game_time']
            if isinstance(game_time, str):
                game_time = datetime.strptime(game_time, '%Y-%m-%dT%H:%M:%SZ')

            print(f"Processing hitter {index + 1}/{len(hitters)}: {hitter_data}")

            hitter = Hitter(
                player_id=hitter_data['player_id'],
                player_name=hitter_data['player_name'],
                team=hitter_data['team'],
                opponent=hitter_data['opponent'],
                opponent_pitcher=hitter_data['opponent_pitcher'],
                opponent_pitcher_hand=hitter_data['opponent_pitcher_hand'],
                game_time=game_time,
                hits_last_10_games=hitter_data['hits_last_10_games'],
                batting_average_vs_handedness=hitter_data['season_avg_vs_handed'],
                batting_average_vs_pitcher=hitter_data['batting_average_vs_pitcher'] or 0.0,  # Ensuring no null values
                hits_vs_pitcher=hitter_data['hits_vs_pitcher'],
                at_bats_vs_pitcher=hitter_data['at_bats_vs_pitcher'],
                combined_score=hitter_data['combined_score'],
                venue_name=hitter_data['venue_name'],
                game_id=hitter_data['game_id']
            )
            db_session.add(hitter)
            stored_hitters.append(hitter)
        except Exception as e:
            print(f"Error adding hitter {hitter_data.get('player_name', 'unknown')} to the session: {e}")

    try:
        db_session.commit()
    except Exception as e:
        print(f"Error committing to the database: {e}")
        db_session.rollback()  # Rollback on error

    return stored_hitters

def store_homers_data(homers):
    stored_homers = []
    
    if not homers:
        print("No homers data to process.")
        return stored_homers

    for index, hitter_data in enumerate(homers):
        try:
            required_keys = ['player_id', 'player_name', 'team', 'opponent', 'opponent_pitcher', 'opponent_pitcher_hand', 'game_time', 'hits_last_10_games', 'home_runs_last_10_games', 'season_avg_vs_handed', 'batting_average_vs_pitcher', 'venue_name', 'homer_score', 'game_id']
            for key in required_keys:
                if key not in hitter_data:
                    raise ValueError(f"Missing required key '{key}' in hitter data: {hitter_data}")

            game_time = hitter_data['game_time']
            if isinstance(game_time, str):
                game_time = datetime.strptime(game_time, '%Y-%m-%dT%H:%M:%SZ')

            print(f"Processing hitter {index + 1}/{len(homers)}: {hitter_data}")

            hitter = Homer(
                player_id=hitter_data['player_id'],
                player_name=hitter_data['player_name'],
                team=hitter_data['team'],
                opponent=hitter_data['opponent'],
                opponent_pitcher=hitter_data['opponent_pitcher'],
                opponent_pitcher_hand=hitter_data['opponent_pitcher_hand'],
                game_time=game_time,
                hits_last_10_games=hitter_data['hits_last_10_games'],
                home_runs_last_10_games=hitter_data['home_runs_last_10_games'],
                batting_average_vs_handedness=hitter_data['season_avg_vs_handed'],
                batting_average_vs_pitcher=hitter_data['batting_average_vs_pitcher'] or 0.0,  # Ensuring no null values
                hits_vs_pitcher=hitter_data['hits_vs_pitcher'],
                at_bats_vs_pitcher=hitter_data['at_bats_vs_pitcher'],
                venue_name=hitter_data['venue_name'],
                homer_score=hitter_data['homer_score'],
                game_id=hitter_data['game_id']
            )
            db_session.add(hitter)
            stored_homers.append(hitter)
        except Exception as e:
            print(f"Error adding hitter {hitter_data.get('player_name', 'unknown')} to the session: {e}")

    try:
        db_session.commit()
    except Exception as e:
        print(f"Error committing to the database: {e}")
        db_session.rollback()  # Rollback on error

    return stored_homers

def _run_hits_core():
    db_session.query(Hitter).delete()
    db_session.query(Homer).delete()
    db_session.commit()
    unique_hitters, homers = fetch_hitters_data()
    filtered_hitters = filter_hitters(unique_hitters)
    filtered_homers = filter_homers(homers)
    store_hitters_data(filtered_hitters)
    store_homers_data(filtered_homers)
    return {
        "candidates": len(unique_hitters),
        "hitters_stored": len(filtered_hitters),
        "homers_stored": len(filtered_homers),
    }


def run() -> dict:
    """Rebuild pred_hitter and pred_homer boards."""
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        stats = _run_hits_core()
        return {"status": "ok", "task": "hits", **stats}
    finally:
        close_session()
