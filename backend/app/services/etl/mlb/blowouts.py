import sys
import os
from datetime import datetime
import requests
from app.models.predictions_models import BlowoutChances

from app.services.etl.mlb._db import db_session
from app.services.etl.mlb.hits import fetch_hitters_data
from app.services.etl.mlb.strikeouts import fetch_pitcher_data
from app.services.etl.mlb._mlb_utils import get_todays_games


def get_team_performance_metrics(team_id):
    try:
        url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?season=2025&group=hitting&stats=season"
        response = requests.get(url)
        data = response.json()

        if "stats" in data and data["stats"]:
            splits = data["stats"][0]["splits"]
            if splits:
                team_stats = splits[0]["stat"]
                games_played = team_stats.get(
                    "gamesPlayed", 1
                )  # Default to 1 to avoid division by zero
                runs = team_stats.get("runs", 0)
                runs_allowed = team_stats.get(
                    "runsAgainst", 0
                )  # Assuming this field exists similarly
                team_avg_runs = runs / games_played
                team_avg_runs_allowed = runs_allowed / games_played
                return team_avg_runs, team_avg_runs_allowed
    except Exception as e:
        print(f"Error fetching team performance metrics for team ID {team_id}: {e}")

    return 0, 0


def flatten_batters(batters):
    return [batter for sublist in batters for batter in sublist]


def evaluate_blowout_chances(pitchers, batters):
    blowout_chances = []
    batters = flatten_batters(batters)

    for game in get_todays_games():
        home_team_id = game["home_id"]
        away_team_id = game["away_id"]
        home_avg_runs, home_avg_runs_allowed = get_team_performance_metrics(
            home_team_id
        )
        away_avg_runs, away_avg_runs_allowed = get_team_performance_metrics(
            away_team_id
        )

        home_pitcher = next(
            (pitcher for pitcher in pitchers if pitcher["team"] == game["home_name"]),
            None,
        )
        away_pitcher = next(
            (pitcher for pitcher in pitchers if pitcher["team"] == game["away_name"]),
            None,
        )

        home_batters = [
            batter for batter in batters if batter["team"] == game["home_name"]
        ]
        away_batters = [
            batter for batter in batters if batter["team"] == game["away_name"]
        ]

        if home_pitcher:
            home_pitcher_effectiveness = calculate_pitcher_effectiveness(
                home_pitcher, away_batters
            )
        else:
            home_pitcher_effectiveness = 0

        if away_pitcher:
            away_pitcher_effectiveness = calculate_pitcher_effectiveness(
                away_pitcher, home_batters
            )
        else:
            away_pitcher_effectiveness = 0

        home_expected_runs = (
            home_avg_runs + away_pitcher_effectiveness - away_avg_runs_allowed
        )
        away_expected_runs = (
            away_avg_runs + home_pitcher_effectiveness - home_avg_runs_allowed
        )
        run_differential = home_expected_runs - away_expected_runs

        blowout_chances.append(
            {
                "game_id": game["game_id"],
                "home_team": game["home_name"],
                "away_team": game["away_name"],
                "home_expected_runs": round(home_expected_runs, 2),
                "away_expected_runs": round(away_expected_runs, 2),
                "home_pitcher_effectiveness": round(home_pitcher_effectiveness, 2),
                "away_pitcher_effectiveness": round(away_pitcher_effectiveness, 2),
                "run_differential": round(run_differential, 2),
                "blowout_team": "home" if run_differential >= 1.5 else "away",
            }
        )

    return blowout_chances


def calculate_pitcher_effectiveness(pitcher, opposing_batters):
    if not pitcher or not opposing_batters:
        return 0

    total_effectiveness = 0
    for batter in opposing_batters:
        batter_avg = batter.get("batting_average_vs_pitcher") or batter.get(
            "season_avg_vs_handed", 0
        )
        total_effectiveness += batter_avg

    average_effectiveness = (
        total_effectiveness / len(opposing_batters) if opposing_batters else 0
    )
    return average_effectiveness


def store_blowout_chances(blowout_chances):
    try:
        for blowout in blowout_chances:
            blowout_entry = BlowoutChances(
                game_id=blowout["game_id"],
                home_team=blowout["home_team"],
                away_team=blowout["away_team"],
                home_expected_runs=blowout["home_expected_runs"],
                away_expected_runs=blowout["away_expected_runs"],
                home_pitcher_effectiveness=blowout["home_pitcher_effectiveness"],
                away_pitcher_effectiveness=blowout["away_pitcher_effectiveness"],
                run_differential=blowout["run_differential"],
                blowout_team=blowout["blowout_team"],
            )
            db_session.add(blowout_entry)
        db_session.commit()
        print("Blowout chances stored successfully.")
    except Exception as e:
        print(f"Error storing blowout chances: {e}")


def main():
    db_session.query(BlowoutChances).delete()
    db_session.commit()
    unique_hitters, _homers = fetch_hitters_data()
    pitchers = fetch_pitcher_data()
    blowout_chances = evaluate_blowout_chances(pitchers, unique_hitters)
    store_blowout_chances(blowout_chances)


if __name__ == "__main__":
    main()


def run() -> dict:
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        main()
        return {"status": "ok", "task": "blowouts"}
    finally:
        close_session()
