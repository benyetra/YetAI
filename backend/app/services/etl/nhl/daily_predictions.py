#!/usr/bin/env python3
"""
NHL Automated Daily Predictions
Runs daily to:
1. Update NHL stats (teams, players, goalies)
2. Generate all predictions (goalies, players, team totals)
3. Fetch current betting lines
4. Store predictions in database
5. Collect actuals from completed games
"""


from app.models.predictions_models import (
    NHLGoaliePredictions,
    NHLGoalieActuals,
    NHLPlayer,
    NHLTeam,
    NHLGoalie,
    NHLGameStats,
)
from app.services.etl.nhl.nhl_api_client import NHLAPIClient
from app.services.etl.nhl.goalie_saves_model import predict_goalie_saves
from app.services.etl.nhl.player_shots_model import predict_player_shots
from app.services.etl.nhl.team_totals_model import predict_team_total_goals
from app.services.etl.nhl.generate_daily_predictions import (
    get_nhl_events_from_odds_api,
    get_goalie_saves_odds_for_event,
    get_player_shots_odds_for_event,
    get_team_totals_odds_for_event,
    get_odds_api_team_name,
)
from datetime import datetime, date, timedelta
from sqlalchemy import and_
from app.services.etl.nhl._db import db_session
import logging
import time
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def update_nhl_stats():
    """Step 1: Update all NHL stats from API"""
    logging.info("=" * 80)
    logging.info("STEP 1: Updating NHL stats")
    logging.info("=" * 80)

    try:
        # Import and run the daily update function
        from app.services.etl.nhl.collect_historical_data import update_daily_stats

        # Update all stats for current season
        update_daily_stats(season=20252026)

        logging.info("✅ NHL stats updated successfully")
        return True

    except Exception as e:
        logging.error(f"❌ Error running stats update: {e}")
        import traceback

        logging.error(traceback.format_exc())
        return False


def generate_goalie_predictions(games, odds_events):
    """Step 2: Generate goalie save predictions with betting lines"""
    logging.info("=" * 80)
    logging.info("STEP 2: Generating goalie save predictions")
    logging.info("=" * 80)

    predictions_generated = 0

    today = date.today()

    # Clear old predictions for today
    db_session.query(NHLGoaliePredictions).filter_by(game_date=today).delete()
    db_session.commit()

    for game in games:
        # Use placeName to match database
        home_team = game["homeTeam"]["placeName"]["default"]
        away_team = game["awayTeam"]["placeName"]["default"]
        home_team_id = game["homeTeam"]["id"]
        away_team_id = game["awayTeam"]["id"]
        home_abbrev = game["homeTeam"]["abbrev"]
        away_abbrev = game["awayTeam"]["abbrev"]

        # Parse game time
        game_time = None
        game_date = today  # Default to today if no time available
        if "startTimeUTC" in game:
            from datetime import datetime

            game_time = datetime.fromisoformat(
                game["startTimeUTC"].replace("Z", "+00:00")
            )
            # Extract the actual game date from the UTC time
            game_date = game_time.date()

        # Get starting goalies from database (#1 goalie = most games played)
        home_goalie = (
            db_session.query(NHLGoalie)
            .filter(NHLGoalie.team_name == home_team, NHLGoalie.games_played > 0)
            .order_by(NHLGoalie.games_played.desc())
            .first()
        )

        away_goalie = (
            db_session.query(NHLGoalie)
            .filter(NHLGoalie.team_name == away_team, NHLGoalie.games_played > 0)
            .order_by(NHLGoalie.games_played.desc())
            .first()
        )

        # Find matching event from odds API
        odds_home = get_odds_api_team_name(home_team, home_abbrev)
        odds_away = get_odds_api_team_name(away_team, away_abbrev)
        event_key = f"{odds_away} @ {odds_home}"

        event_id = None
        for event in odds_events:
            if f"{event['away_team']} @ {event['home_team']}" == event_key:
                event_id = event["id"]
                break

        # Fetch goalie betting lines
        goalie_lines = {}
        if event_id:
            goalie_lines = get_goalie_saves_odds_for_event(
                event_id, odds_home, odds_away
            )

        # Generate predictions for both goalies
        for is_home, goalie, team_name, team_id, opponent, opponent_id in [
            (True, home_goalie, home_team, home_team_id, away_team, away_team_id),
            (False, away_goalie, away_team, away_team_id, home_team, home_team_id),
        ]:
            if not goalie:
                logging.warning(f"⚠️  No goalie found for {team_name}")
                continue

            goalie_id = goalie.player_id
            goalie_name = goalie.name

            # Generate prediction
            try:
                prediction = predict_goalie_saves(
                    goalie_id=goalie_id,
                    goalie_name=goalie_name,
                    opponent_team_name=opponent,
                    game_date=today,
                    is_home=is_home,
                    goalie_team_name=team_name,
                )

                if "error" not in prediction:
                    # Get betting line for this goalie
                    line_data = goalie_lines.get(goalie_name, {})
                    from app.services.etl.nhl.betting_edges import (
                        recommendation_for_saves,
                    )

                    saves_line = line_data.get("line")
                    edge_info = recommendation_for_saves(
                        prediction["predicted_saves"], saves_line
                    )

                    # Save to database
                    db_pred = NHLGoaliePredictions(
                        game_date=game_date,
                        game_time=game_time,
                        goalie_id=goalie_id,
                        goalie_name=goalie_name,
                        team_id=team_id,
                        team_name=team_name,
                        opponent_team_id=opponent_id,
                        opponent_team_name=opponent,
                        is_home=is_home,
                        predicted_saves=prediction["predicted_saves"],
                        predicted_shots_against=prediction["predicted_shots_against"],
                        predicted_save_pct=prediction.get("predicted_save_pct", 0.0),
                        goalie_season_save_pct=prediction.get("goalie_season_save_pct"),
                        confidence=prediction["confidence"],
                        saves_line=saves_line,
                        over_odds=line_data.get("over_odds"),
                        under_odds=line_data.get("under_odds"),
                        edge_saves=edge_info.edge_value,
                        edge_category=edge_info.edge_category,
                        betting_recommendation=edge_info.recommendation,
                    )
                    db_session.add(db_pred)
                    predictions_generated += 1
                    logging.info(
                        f"✅ {goalie_name}: {prediction['predicted_saves']:.1f} saves predicted"
                    )

            except Exception as e:
                logging.error(f"❌ Error predicting for {goalie_name}: {e}")
                continue

    db_session.commit()
    logging.info(f"✅ Generated {predictions_generated} goalie predictions")
    return predictions_generated


def generate_player_predictions(games, odds_events):
    """Step 3: Generate player shots predictions and save to database"""
    logging.info("=" * 80)
    logging.info("STEP 3: Generating player shots predictions")
    logging.info("=" * 80)

    from app.models.predictions_models import NHLPlayerShotsPredictions
    from app.services.etl.nhl.betting_edges import recommendation_for_shots
    from app.services.etl.nhl.generate_daily_predictions import (
        get_odds_api_team_name,
        get_player_shots_odds_for_event,
    )

    predictions_generated = 0
    today = date.today()

    odds_lookup = {}
    for event in odds_events:
        key = f"{event['away_team']} @ {event['home_team']}"
        odds_lookup[key] = event

    # Delete old predictions for today (in case re-running)
    db_session.query(NHLPlayerShotsPredictions).filter_by(game_date=today).delete()
    db_session.commit()

    for game in games:
        # Get team IDs to look up players
        home_team_id = game["homeTeam"]["id"]
        away_team_id = game["awayTeam"]["id"]
        home_abbrev = game["homeTeam"]["abbrev"]
        away_abbrev = game["awayTeam"]["abbrev"]
        home_team_name = game["homeTeam"]["placeName"]["default"]
        away_team_name = game["awayTeam"]["placeName"]["default"]

        # Parse game time
        game_time_et = None
        game_date = today  # Default to today if no time available
        if "startTimeUTC" in game:
            from datetime import datetime

            game_time_et = datetime.fromisoformat(
                game["startTimeUTC"].replace("Z", "+00:00")
            )
            # Extract the actual game date from the UTC time
            game_date = game_time_et.date()

        logging.info(f"📊 Processing game: {away_team_name} @ {home_team_name}")

        odds_home = get_odds_api_team_name(home_team_name, home_abbrev)
        odds_away = get_odds_api_team_name(away_team_name, away_abbrev)
        odds_key = f"{odds_away} @ {odds_home}"
        player_lines: dict = {}
        if odds_key in odds_lookup:
            event_id = odds_lookup[odds_key]["id"]
            player_lines = get_player_shots_odds_for_event(
                event_id, odds_home, odds_away
            )

        # Get top scorers from each team (from our database)
        for team_id, team_name, opponent_name, is_home in [
            (home_team_id, home_team_name, away_team_name, True),
            (away_team_id, away_team_name, home_team_name, False),
        ]:
            # Get top 5 players by shots per game for this team
            players = (
                db_session.query(NHLPlayer)
                .filter(NHLPlayer.team_id == team_id, NHLPlayer.shots_per_game > 0)
                .order_by(NHLPlayer.shots_per_game.desc())
                .limit(5)
                .all()
            )

            logging.info(
                f"  Found {len(players)} players for {team_name} (team_id={team_id})"
            )

            for player in players:
                try:
                    pred = predict_player_shots(
                        player_id=player.player_id,
                        opponent_team_name=opponent_name,
                        is_home=is_home,
                    )
                    if "error" not in pred:
                        line_data = player_lines.get(pred["player_name"], {})
                        shots_line = line_data.get("line")
                        edge_info = recommendation_for_shots(
                            pred["predicted_shots"], shots_line
                        )
                        # Save to database
                        db_pred = NHLPlayerShotsPredictions(
                            game_date=game_date,
                            game_time_et=game_time_et,
                            player_id=player.player_id,
                            player_name=pred["player_name"],
                            team_name=team_name,
                            opponent_team_name=opponent_name,
                            predicted_shots=pred["predicted_shots"],
                            shots_line=shots_line,
                            betting_recommendation=edge_info.recommendation,
                            confidence=pred.get("confidence", 0.0),
                        )
                        db_session.add(db_pred)
                        predictions_generated += 1
                        logging.info(
                            f"✅ {pred['player_name']}: {pred['predicted_shots']:.1f} shots predicted"
                        )
                    else:
                        logging.warning(
                            f"⚠️  Error in prediction for {player.name}: {pred.get('error')}"
                        )
                except Exception as e:
                    logging.error(f"❌ Error predicting for player {player.name}: {e}")
                    import traceback

                    logging.error(traceback.format_exc())
                    continue

    db_session.commit()

    logging.info(f"✅ Generated and saved {predictions_generated} player predictions")
    return predictions_generated


def generate_team_totals_predictions(games, odds_events):
    """Step 4: Generate team totals predictions and save to database"""
    logging.info("=" * 80)
    logging.info("STEP 4: Generating team totals predictions")
    logging.info("=" * 80)

    from app.models.predictions_models import NHLTeamTotalsPredictions
    from app.services.etl.nhl.betting_edges import recommendation_for_total_goals
    from app.services.etl.nhl.generate_daily_predictions import (
        get_team_totals_odds_for_event,
        get_odds_api_team_name,
    )

    # Create lookup for odds by team names
    odds_lookup = {}
    for event in odds_events:
        key = f"{event['away_team']} @ {event['home_team']}"
        odds_lookup[key] = event

    predictions_generated = 0
    today = date.today()

    # Delete old predictions for today (in case re-running)
    db_session.query(NHLTeamTotalsPredictions).filter_by(game_date=today).delete()
    db_session.commit()

    for game in games:
        # Use placeName (city) not commonName (team nickname) to match database
        home_team = game["homeTeam"]["placeName"]["default"]
        away_team = game["awayTeam"]["placeName"]["default"]
        home_team_id = game["homeTeam"]["id"]
        away_team_id = game["awayTeam"]["id"]
        home_abbrev = game["homeTeam"]["abbrev"]
        away_abbrev = game["awayTeam"]["abbrev"]

        # Parse game time
        game_time_et = None
        game_date = today  # Default to today if no time available
        if "startTimeUTC" in game:
            from datetime import datetime

            game_time_et = datetime.fromisoformat(
                game["startTimeUTC"].replace("Z", "+00:00")
            )
            # Extract the actual game date from the UTC time
            game_date = game_time_et.date()

        try:
            pred = predict_team_total_goals(
                home_team_name=home_team, away_team_name=away_team, game_date=game_date
            )

            if "error" not in pred:
                # Look up DraftKings O/U line
                draftkings_ou_line = None
                over_odds = None
                under_odds = None

                odds_home = get_odds_api_team_name(home_team, home_abbrev)
                odds_away = get_odds_api_team_name(away_team, away_abbrev)
                odds_key = f"{odds_away} @ {odds_home}"

                if odds_key in odds_lookup:
                    event_id = odds_lookup[odds_key]["id"]
                    totals_odds = get_team_totals_odds_for_event(
                        event_id, odds_home, odds_away
                    )

                    if totals_odds and "line" in totals_odds:
                        draftkings_ou_line = totals_odds["line"]
                        over_odds = totals_odds.get("over_odds")
                        under_odds = totals_odds.get("under_odds")

                # Calculate edge
                edge = None
                if draftkings_ou_line:
                    edge = pred["predicted_total_goals"] - draftkings_ou_line

                totals_edge = recommendation_for_total_goals(
                    pred["predicted_total_goals"], draftkings_ou_line, edge
                )

                # Save to database
                db_pred = NHLTeamTotalsPredictions(
                    game_date=game_date,
                    game_time_et=game_time_et,
                    home_team_id=home_team_id,
                    home_team_name=home_team,
                    away_team_id=away_team_id,
                    away_team_name=away_team,
                    predicted_home_goals=pred["predicted_home_goals"],
                    predicted_away_goals=pred["predicted_away_goals"],
                    predicted_total_goals=pred["predicted_total_goals"],
                    suggested_ou_line=pred["suggested_ou_line"],
                    draftkings_ou_line=draftkings_ou_line,
                    over_odds=over_odds,
                    under_odds=under_odds,
                    confidence=pred.get("confidence", 0.0),
                    edge=edge,
                    betting_recommendation=totals_edge.recommendation,
                )
                db_session.add(db_pred)
                predictions_generated += 1
                logging.info(
                    f"✅ {away_team} @ {home_team}: {pred['predicted_total_goals']:.1f} total goals predicted"
                )
                logging.info(
                    f"   Home: {pred['predicted_home_goals']:.1f}, Away: {pred['predicted_away_goals']:.1f}"
                )
                logging.info(f"   Suggested O/U: {pred['suggested_ou_line']:.1f}")

        except Exception as e:
            logging.error(f"❌ Error predicting for {away_team} @ {home_team}: {e}")
            import traceback

            logging.error(traceback.format_exc())
            continue

    db_session.commit()

    logging.info(
        f"✅ Generated and saved {predictions_generated} team totals predictions"
    )
    return predictions_generated


def collect_actuals_from_completed_games():
    """Step 5: Collect actual results from yesterday's games"""
    logging.info("=" * 80)
    logging.info("STEP 5: Collecting actuals from completed games")
    logging.info("=" * 80)

    try:
        yesterday = date.today() - timedelta(days=1)

        # Get yesterday's schedule
        url = f"https://api-web.nhle.com/v1/schedule/{yesterday.strftime('%Y-%m-%d')}"
        response = requests.get(url)
        response.raise_for_status()
        schedule_data = response.json()

        # Find completed games
        completed_games = []
        if "gameWeek" in schedule_data:
            for game_day in schedule_data["gameWeek"]:
                if "games" in game_day:
                    for game in game_day["games"]:
                        if game.get("gameState") in ["OFF", "FINAL"]:
                            completed_games.append(game)

        logging.info(
            f"📊 Found {len(completed_games)} completed games from {yesterday}"
        )

        actuals_saved = 0

        for game in completed_games:
            game_id = game["id"]

            # Get detailed boxscore
            boxscore_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
            box_response = requests.get(boxscore_url)

            if box_response.status_code != 200:
                logging.warning(f"⚠️  Could not fetch boxscore for game {game_id}")
                continue

            box_data = box_response.json()

            if "playerByGameStats" not in box_data:
                continue

            # Extract team info
            away_team = box_data.get("awayTeam", {})
            home_team = box_data.get("homeTeam", {})

            # Process away team goalies
            if "awayTeam" in box_data["playerByGameStats"]:
                for position, players in box_data["playerByGameStats"][
                    "awayTeam"
                ].items():
                    if position == "goalies":
                        for goalie in players:
                            actuals_saved += save_goalie_actual(
                                goalie,
                                game_id,
                                yesterday,
                                away_team.get("placeName", {}).get("default", ""),
                                home_team.get("placeName", {}).get("default", ""),
                            )

            # Process home team goalies
            if "homeTeam" in box_data["playerByGameStats"]:
                for position, players in box_data["playerByGameStats"][
                    "homeTeam"
                ].items():
                    if position == "goalies":
                        for goalie in players:
                            actuals_saved += save_goalie_actual(
                                goalie,
                                game_id,
                                yesterday,
                                home_team.get("placeName", {}).get("default", ""),
                                away_team.get("placeName", {}).get("default", ""),
                            )

        db_session.commit()

        logging.info(f"✅ Saved {actuals_saved} goalie actual results")
        return actuals_saved

    except Exception as e:
        logging.error(f"❌ Error collecting actuals: {e}")
        import traceback

        logging.error(traceback.format_exc())
        return 0


def save_goalie_actual(goalie, game_id, game_date, team_name, opponent_name):
    """Save a single goalie actual result to database"""
    try:
        goalie_id = goalie.get("playerId")
        goalie_name = goalie.get("name", {}).get("default", "")

        # Skip if played less than 10 minutes
        toi = goalie.get("toi", "0:00")
        toi_parts = toi.split(":")
        if len(toi_parts) == 2:
            minutes = int(toi_parts[0])
            if minutes < 10:
                logging.info(f"⏭️  Skipping {goalie_name} - only played {toi}")
                return 0

        # Check if already exists
        existing = (
            db_session.query(NHLGoalieActuals)
            .filter(
                and_(
                    NHLGoalieActuals.game_id == game_id,
                    NHLGoalieActuals.goalie_id == goalie_id,
                )
            )
            .first()
        )

        if existing:
            logging.info(f"⏭️  Result already exists for {goalie_name}")
            return 0

        # Find matching prediction
        prediction = (
            db_session.query(NHLGoaliePredictions)
            .filter(
                and_(
                    NHLGoaliePredictions.goalie_name == goalie_name,
                    NHLGoaliePredictions.game_date == game_date,
                )
            )
            .first()
        )

        # Create actual record
        actual = NHLGoalieActuals(
            game_id=game_id,
            game_date=game_date,
            goalie_id=goalie_id,
            goalie_name=goalie_name,
            team_name=team_name,
            opponent_team_name=opponent_name,
            actual_saves=goalie.get("saves", 0),
            actual_shots_against=goalie.get("shotsAgainst", 0),
            actual_save_pct=goalie.get("savePctg", 0.0),
            actual_goals_against=goalie.get("goalsAgainst", 0),
            actual_toi=toi,
            decision=goalie.get("decision", ""),
            predicted_saves=prediction.predicted_saves if prediction else None,
            predicted_shots_against=(
                prediction.predicted_shots_against if prediction else None
            ),
            prediction_error=(
                goalie.get("saves", 0) - prediction.predicted_saves
                if prediction
                else None
            ),
            prediction_correct=(
                abs(goalie.get("saves", 0) - prediction.predicted_saves) <= 2
                if prediction
                else None
            ),
        )

        db_session.add(actual)
        logging.info(
            f"✅ {goalie_name}: {actual.actual_saves} saves (predicted: {actual.predicted_saves or 'N/A'})"
        )
        return 1

    except Exception as e:
        logging.error(f"❌ Error saving actual for {goalie_name}: {e}")
        return 0


def _run_daily_core():
    """Main automation function - runs daily"""
    logging.info("\n" + "=" * 80)
    logging.info("NHL AUTOMATED DAILY PREDICTIONS")
    logging.info(f"Running at: {datetime.now()}")
    logging.info("=" * 80 + "\n")

    # Initialize NHL API client
    client = NHLAPIClient()

    # Get today's schedule
    logging.info("Fetching today's NHL schedule...")
    schedule = client.get_schedule()

    if not schedule or "gameWeek" not in schedule:
        logging.warning("⚠️  No NHL games scheduled for today")
        return

    # Extract games
    games = []
    for game_day in schedule["gameWeek"]:
        games.extend(game_day.get("games", []))

    if not games:
        logging.warning("⚠️  No games found in schedule")
        return

    logging.info(f"📅 Found {len(games)} games scheduled for today\n")

    # Fetch betting odds events
    logging.info("Fetching betting odds from The Odds API...")
    odds_events = get_nhl_events_from_odds_api()
    logging.info(f"📊 Found {len(odds_events)} events in odds feed\n")

    # Run all steps
    stats_updated = update_nhl_stats()

    if stats_updated:
        goalie_count = generate_goalie_predictions(games, odds_events)
        time.sleep(2)  # Rate limit

        player_count = generate_player_predictions(games, odds_events)
        time.sleep(2)  # Rate limit

        team_count = generate_team_totals_predictions(games, odds_events)
        time.sleep(2)  # Rate limit

        actuals_count = collect_actuals_from_completed_games()
    else:
        logging.error("❌ Stats update failed, skipping predictions")
        return

    # Summary
    logging.info("\n" + "=" * 80)
    logging.info("AUTOMATION COMPLETE")
    logging.info("=" * 80)
    logging.info(f"✅ Goalie predictions: {goalie_count}")
    logging.info(f"✅ Player predictions: {player_count}")
    logging.info(f"✅ Team totals predictions: {team_count}")
    logging.info(f"✅ Actuals collected: {actuals_count}")
    logging.info("=" * 80 + "\n")


if __name__ == "__main__":
    from app.services.etl.nhl._db import init_session, close_session

    init_session()
    try:
        _run_daily_core()
    finally:
        close_session()


def run() -> dict:
    from app.services.etl.nhl._db import close_session, init_session

    init_session()
    try:
        _run_daily_core()
        return {"status": "ok", "task": "nhl_daily_predictions"}
    finally:
        close_session()
