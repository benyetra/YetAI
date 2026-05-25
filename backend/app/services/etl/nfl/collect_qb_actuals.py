#!/usr/bin/env python3
"""
QB Actuals Collection Script
Collects actual QB performance and compares with predictions

This script will:
1. Get actual QB stats from NFLverse
2. Match with our historical predictions
3. Calculate accuracy metrics
4. Save to QBActuals table
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import warnings

warnings.filterwarnings("ignore")

# Add parent directories to path

from app.services.etl.nfl._db import db_session
from app.models.predictions_models import QBPredictions, QBActuals
from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season

try:
    import nfl_data_py as nfl
except ImportError:
    raise SystemExit("nfl_data_py not installed. Run: pip install nfl-data-py")


def collect_qb_game_stats(season: int, week: int) -> List[Dict]:
    """
    Collect QB stats from NFLverse for a specific week
    """
    print(f"📡 Collecting QB stats for {season} Week {week}...")

    try:
        # Get play-by-play data for the week
        pbp_data = nfl.import_pbp_data([season])

        # Filter for the specific week and passing plays
        week_data = pbp_data[
            (pbp_data["season"] == season)
            & (pbp_data["week"] == week)
            & (pbp_data["play_type"] == "pass")
            & (pbp_data["passer_player_name"].notna())
        ]

        if week_data.empty:
            print(f"⚠️ No passing data found for Week {week}")
            return []

        # Aggregate QB stats
        qb_stats = (
            week_data.groupby(["passer_player_id", "passer_player_name", "posteam"])
            .agg(
                {
                    "passing_yards": "sum",
                    "complete_pass": "sum",
                    "incomplete_pass": "sum",
                    "pass_attempt": "sum",
                    "pass_touchdown": "sum",
                    "interception": "sum",
                    "epa": "mean",
                    "cpoe": "mean",
                    "air_yards": "mean",
                }
            )
            .reset_index()
        )

        # Calculate additional metrics
        qb_stats["completion_pct"] = (
            qb_stats["complete_pass"] / qb_stats["pass_attempt"]
        ) * 100
        qb_stats["yards_per_attempt"] = (
            qb_stats["passing_yards"] / qb_stats["pass_attempt"]
        )

        # Calculate passer rating (simplified version)
        qb_stats["passer_rating"] = (
            ((qb_stats["completion_pct"] - 30) * 0.05)
            + ((qb_stats["yards_per_attempt"] - 3) * 0.25)
            + (qb_stats["pass_touchdown"] / qb_stats["pass_attempt"] * 20)
            - (qb_stats["interception"] / qb_stats["pass_attempt"] * 25)
        ).clip(0, 158.3)

        # Get opponent info from schedule
        schedules = nfl.import_schedules([season])
        week_schedule = schedules[schedules["week"] == week]

        results = []
        for _, qb_row in qb_stats.iterrows():
            # Find opponent for this QB's team
            team_games = week_schedule[
                (week_schedule["home_team"] == qb_row["posteam"])
                | (week_schedule["away_team"] == qb_row["posteam"])
            ]

            if not team_games.empty:
                game = team_games.iloc[0]
                opponent = (
                    game["away_team"]
                    if game["home_team"] == qb_row["posteam"]
                    else game["home_team"]
                )
                venue = game.get("stadium", "Unknown")
                game_date = game.get("gameday", datetime.now().date())

                results.append(
                    {
                        "qb_player_id": str(qb_row["passer_player_id"]),
                        "qb_player_name": qb_row["passer_player_name"],
                        "team_name": qb_row["posteam"],
                        "opponent_team_name": opponent,
                        "venue_name": venue,
                        "game_date": game_date,
                        "season": season,
                        "week": week,
                        "actual_passing_yards": float(qb_row["passing_yards"]),
                        "actual_attempts": int(qb_row["pass_attempt"]),
                        "actual_completions": int(qb_row["complete_pass"]),
                        "actual_touchdowns": int(qb_row["pass_touchdown"]),
                        "actual_interceptions": int(qb_row["interception"]),
                        "actual_completion_pct": float(qb_row["completion_pct"]),
                        "actual_yards_per_attempt": float(qb_row["yards_per_attempt"]),
                        "actual_passer_rating": float(qb_row["passer_rating"]),
                        "epa_per_play": float(qb_row["epa"]),
                        "cpoe": float(qb_row["cpoe"]),
                        "air_yards_per_attempt": float(qb_row["air_yards"]),
                    }
                )

        print(f"✅ Collected stats for {len(results)} quarterbacks")
        return results

    except Exception as e:
        print(f"❌ Error collecting QB stats: {e}")
        return []


def create_name_mapping() -> Dict[str, str]:
    """
    Create mapping from NFLverse abbreviated names to full names
    """
    name_mapping = {
        "A.Rodgers": "Aaron Rodgers",
        "J.Flacco": "Joe Flacco",
        "M.Stafford": "Matthew Stafford",
        "T.Taylor": "Tyrod Taylor",
        "K.Cousins": "Kirk Cousins",
        "G.Smith": "Geno Smith",
        "M.Mariota": "Marcus Mariota",
        "C.Wentz": "Carson Wentz",
        "B.Mayfield": "Baker Mayfield",
        "J.Allen": "Josh Allen",
        "B.Rypien": "Brett Rypien",
        "J.Browning": "Jake Browning",
        "D.Jones": "Daniel Jones",
        "T.Tagovailoa": "Tua Tagovailoa",
        "J.Love": "Jordan Love",
        "J.Hurts": "Jalen Hurts",
        "T.Lawrence": "Trevor Lawrence",
        "B.Young": "Bryce Young",
        "C.Stroud": "C.J. Stroud",
        "D.Maye": "Drake Maye",
        "M.Penix": "Michael Penix Jr.",
        "M.Brosmer": "Max Brosmer",
        "C.Ward": "Cam Ward",
        "P.Mahomes": "Patrick Mahomes",
        "J.Herbert": "Justin Herbert",
        "L.Jackson": "Lamar Jackson",
        "J.Burrow": "Joe Burrow",
        "R.Wilson": "Russell Wilson",
        "D.Watson": "Deshaun Watson",
        "C.Williams": "Caleb Williams",
        "J.Daniels": "Jayden Daniels",
        "S.Darnold": "Sam Darnold",
        "J.Goff": "Jared Goff",
        "D.Prescott": "Dak Prescott",
        "B.Purdy": "Brock Purdy",
        "K.Murray": "Kyler Murray",
        "D.Carr": "Derek Carr",
        "A.Richardson": "Anthony Richardson",
        "W.Levis": "Will Levis",
        "G.Minshew": "Gardner Minshew",
        "B.Nix": "Bo Nix",
    }
    return name_mapping


def match_predictions_with_actuals(
    qb_actuals: List[Dict], season: int, week: int
) -> List[Dict]:
    """
    Match actual QB performance with our predictions
    """
    print(f"🔍 Matching predictions with actuals for Week {week}...")

    name_mapping = create_name_mapping()
    matched_results = []

    for actual in qb_actuals:
        try:
            # Convert NFLverse name to full name
            nflverse_name = actual["qb_player_name"]
            full_name = name_mapping.get(nflverse_name, nflverse_name)

            # Find corresponding prediction by name
            prediction = (
                db_session.query(QBPredictions)
                .filter_by(qb_player_name=full_name, season=season, week=week)
                .first()
            )

            if prediction:
                # Calculate prediction accuracy
                predicted_yards = float(prediction.predicted_passing_yards)
                actual_yards = float(actual["actual_passing_yards"])

                prediction_error = actual_yards - predicted_yards
                prediction_accuracy = (
                    abs(prediction_error) / actual_yards if actual_yards > 0 else 0
                )

                # Determine if betting recommendation was correct
                correct_prediction = False
                hit_over_under = None

                if prediction.betting_recommendation and prediction.ou_line:
                    # Check if betting recommendation was correct
                    ou_line = float(prediction.ou_line)

                    if prediction.betting_recommendation == "OVER":
                        # OVER bet wins if actual yards > O/U line
                        hit_over_under = actual_yards > ou_line
                        correct_prediction = hit_over_under
                    elif prediction.betting_recommendation == "UNDER":
                        # UNDER bet wins if actual yards < O/U line
                        hit_over_under = actual_yards < ou_line
                        correct_prediction = hit_over_under
                    elif prediction.betting_recommendation == "PASS":
                        # PASS recommendation is always "correct" (no bet placed)
                        correct_prediction = True
                else:
                    # Fallback to accuracy-based prediction if no betting data
                    accuracy_threshold = min(
                        0.15 * actual_yards, 20
                    )  # 15% or 20 yards, whichever is smaller
                    correct_prediction = abs(prediction_error) <= accuracy_threshold

                # Add prediction info to actual data
                actual.update(
                    {
                        "predicted_passing_yards": predicted_yards,
                        "prediction_error": prediction_error,
                        "prediction_accuracy": prediction_accuracy,
                        "correct_prediction": correct_prediction,
                        "hit_over_under": hit_over_under,
                        "prediction_confidence": float(
                            prediction.model_confidence or 0.5
                        ),
                        "prediction_method": prediction.prediction_method or "unknown",
                        "betting_recommendation": prediction.betting_recommendation,
                        "ou_line": (
                            float(prediction.ou_line) if prediction.ou_line else None
                        ),
                    }
                )

                matched_results.append(actual)
                bet_result = ""
                if prediction.betting_recommendation and prediction.ou_line:
                    bet_status = "✅ WIN" if correct_prediction else "❌ LOSS"
                    if prediction.betting_recommendation == "PASS":
                        bet_status = "🚫 PASS"
                    bet_result = f" | {prediction.betting_recommendation} {prediction.ou_line} {bet_status}"

                print(
                    f"  ✅ {actual['qb_player_name']}: {actual_yards} yards "
                    f"(predicted: {predicted_yards}, error: {prediction_error:+.1f}){bet_result}"
                )
            else:
                print(f"  ⚠️ No prediction found for {actual['qb_player_name']}")

        except Exception as e:
            print(f"  ❌ Error matching {actual['qb_player_name']}: {e}")

    print(f"🎯 Matched {len(matched_results)} QB predictions with actuals")
    return matched_results


def save_qb_actuals(qb_results: List[Dict]) -> Dict:
    """
    Save QB actuals to database
    """
    print("💾 Saving QB actuals to database...")

    results = {
        "saved_qbs": 0,
        "errors": [],
        "accuracy_stats": {
            "total_predictions": 0,
            "correct_predictions": 0,
            "average_error": 0,
            "average_accuracy": 0,
        },
    }

    total_error = 0
    total_accuracy = 0

    for qb_data in qb_results:
        try:
            # Check if actual result already exists
            existing_actual = (
                db_session.query(QBActuals)
                .filter_by(
                    qb_player_id=qb_data["qb_player_id"],
                    season=qb_data["season"],
                    week=qb_data["week"],
                )
                .first()
            )

            if existing_actual:
                print(
                    f"  ⚠️ Actual result already exists for {qb_data['qb_player_name']} Week {qb_data['week']}"
                )
                continue

            # Create new QB actual record
            qb_actual = QBActuals(
                game_date=qb_data["game_date"],
                qb_player_id=qb_data["qb_player_id"],
                qb_player_name=qb_data["qb_player_name"],
                team_name=qb_data["team_name"],
                opponent_team_name=qb_data["opponent_team_name"],
                venue_name=qb_data["venue_name"],
                season=qb_data["season"],
                week=qb_data["week"],
                actual_passing_yards=qb_data["actual_passing_yards"],
                actual_attempts=qb_data["actual_attempts"],
                actual_completions=qb_data["actual_completions"],
                actual_touchdowns=qb_data["actual_touchdowns"],
                actual_interceptions=qb_data["actual_interceptions"],
                actual_completion_pct=qb_data["actual_completion_pct"],
                actual_yards_per_attempt=qb_data["actual_yards_per_attempt"],
                actual_passer_rating=qb_data["actual_passer_rating"],
                predicted_passing_yards=qb_data.get("predicted_passing_yards", 0),
                prediction_error=qb_data.get("prediction_error", 0),
                prediction_accuracy=qb_data.get("prediction_accuracy", 0),
                correct_prediction=qb_data.get("correct_prediction", False),
                hit_over_under=qb_data.get("hit_over_under"),
                prediction_confidence=qb_data.get("prediction_confidence", 0.5),
                prediction_method=qb_data.get("prediction_method", "unknown"),
                epa_per_play=qb_data.get("epa_per_play"),
                cpoe=qb_data.get("cpoe"),
                air_yards_per_attempt=qb_data.get("air_yards_per_attempt"),
                data_collection_date=datetime.utcnow(),
            )

            db_session.add(qb_actual)
            db_session.commit()

            results["saved_qbs"] += 1

            # Update accuracy stats
            if "predicted_passing_yards" in qb_data:
                results["accuracy_stats"]["total_predictions"] += 1
                if qb_data.get("correct_prediction"):
                    results["accuracy_stats"]["correct_predictions"] += 1
                total_error += abs(qb_data.get("prediction_error", 0))
                total_accuracy += qb_data.get("prediction_accuracy", 0)

            print(f"  ✅ Saved actual result for {qb_data['qb_player_name']}")

        except Exception as e:
            error_msg = f"Error saving {qb_data['qb_player_name']}: {e}"
            print(f"  ❌ {error_msg}")
            results["errors"].append(error_msg)
            db_session.rollback()

    # Calculate final accuracy stats
    if results["accuracy_stats"]["total_predictions"] > 0:
        results["accuracy_stats"]["accuracy_rate"] = (
            results["accuracy_stats"]["correct_predictions"]
            / results["accuracy_stats"]["total_predictions"]
        )
        results["accuracy_stats"]["average_error"] = (
            total_error / results["accuracy_stats"]["total_predictions"]
        )
        results["accuracy_stats"]["average_accuracy"] = (
            total_accuracy / results["accuracy_stats"]["total_predictions"]
        )

    return results


def _run_qb_actuals_core():
    """
    Main function to collect QB actuals
    """
    print("🏈 QB Actuals Collection Script")
    print("=" * 50)

    season = get_nfl_season()
    week = get_current_nfl_week(season)

    print(f"📅 Collecting actuals for {season} Week {week}")

    # Collect QB stats from NFLverse
    qb_actuals = collect_qb_game_stats(season, week)

    if not qb_actuals:
        print("❌ No QB actuals collected. Exiting.")
        return

    # Match with predictions
    matched_results = match_predictions_with_actuals(qb_actuals, season, week)

    # Save to database
    save_results = save_qb_actuals(matched_results)

    # Print summary
    print(f"\n{'=' * 50}")
    print("📊 COLLECTION SUMMARY")
    print(f"{'=' * 50}")
    print(f"QBs with actuals collected: {len(qb_actuals)}")
    print(f"QBs matched with predictions: {len(matched_results)}")
    print(f"QBs saved to database: {save_results['saved_qbs']}")
    print(f"Errors: {len(save_results['errors'])}")

    if save_results["accuracy_stats"]["total_predictions"] > 0:
        stats = save_results["accuracy_stats"]
        print(f"\n🎯 PREDICTION ACCURACY")
        print(f"Total predictions: {stats['total_predictions']}")
        print(f"Correct predictions: {stats['correct_predictions']}")
        print(f"Accuracy rate: {stats['accuracy_rate']:.1%}")
        print(f"Average error: {stats['average_error']:.1f} yards")
        print(f"Average accuracy: {stats['average_accuracy']:.1%}")

    if save_results["errors"]:
        print(f"\n❌ ERRORS:")
        for error in save_results["errors"]:
            print(f"  - {error}")

    print(f"\n✅ QB actuals collection complete!")


if __name__ == "__main__":
    from app.services.etl.nfl._db import close_session, init_session

    init_session()
    try:
        _run_qb_actuals_core()
    finally:
        close_session()


def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session

    init_session()
    try:
        _run_qb_actuals_core()
        return {"status": "ok", "task": "nfl_collect_qb_actuals"}
    finally:
        close_session()
