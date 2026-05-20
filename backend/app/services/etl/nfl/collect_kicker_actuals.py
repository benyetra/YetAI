#!/usr/bin/env python3
"""
NFL Kicker Actuals Collection Script
Collects actual field goal performance data and compares with predictions
"""

import pandas as pd
from datetime import datetime, date, timedelta
import nfl_data_py as nfl

# Add parent directories to path

from app.services.etl.nfl._db import db_session
from app.models.predictions_models import Kickers, KickerActuals, KickerPredictions
from sqlalchemy import and_


def get_current_nfl_week(season=2025):
    """
    Calculate the current NFL week based on today's date.

    Args:
        season (int): NFL season year

    Returns:
        int: Current NFL week (1-18), or None if it's off-season
    """
    today = date.today()

    # NFL 2025 season starts around September 5, 2025 (Week 1)
    # This is typically the first Thursday after Labor Day
    if season == 2025:
        # Week 1 starts September 5, 2025 (Thursday Night Football)
        season_start = date(2025, 9, 5)
    elif season == 2024:
        # Week 1 started September 5, 2024
        season_start = date(2024, 9, 5)
    else:
        # For future seasons, estimate first Thursday after Labor Day
        # Labor Day is first Monday in September
        labor_day = date(season, 9, 1)
        while labor_day.weekday() != 0:  # 0 is Monday
            labor_day += timedelta(days=1)

        # First Thursday after Labor Day
        season_start = labor_day + timedelta(days=3)

    # Calculate weeks since season start
    if today < season_start:
        print(f"🏈 Current date ({today}) is before season start ({season_start})")
        return None

    days_since_start = (today - season_start).days
    current_week = (days_since_start // 7) + 1

    # Regular season is weeks 1-18, playoffs are weeks 19-22
    if current_week > 22:
        print(f"🏈 Current date ({today}) is after season end")
        return None

    print(
        f"🏈 Current NFL week: {current_week} (Season {season}, Today: {today}, Season start: {season_start}, Days diff: {days_since_start})"
    )
    return current_week


def get_weekly_field_goal_data(week=None, season=2025):
    """
    Get field goal data for a specific week

    Args:
        week (int): NFL week number (1-18), if None gets current week
        season (int): NFL season year

    Returns:
        DataFrame: Field goal attempts and results
    """
    try:
        print(f"Fetching NFL field goal data for week {week} of {season}...")

        # Get play-by-play data for the week
        if week:
            pbp_data = nfl.import_pbp_data([season])
            pbp_data = pbp_data[pbp_data["week"] == week]
        else:
            # Get current week data
            pbp_data = nfl.import_pbp_data([season])
            current_week = get_current_nfl_week()
            pbp_data = pbp_data[pbp_data["week"] == current_week]

        # Filter for field goal attempts
        fg_data = pbp_data[pbp_data["field_goal_attempt"] == 1].copy()

        if fg_data.empty:
            print(f"No field goal data found for week {week}")
            return pd.DataFrame()

        print(f"Found {len(fg_data)} field goal attempts")

        # Group by kicker and game to get weekly totals
        weekly_stats = (
            fg_data.groupby(
                [
                    "kicker_player_id",
                    "kicker_player_name",
                    "posteam",
                    "defteam",
                    "game_date",
                ]
            )
            .agg(
                {
                    "field_goal_attempt": "sum",
                    "field_goal_result": lambda x: (
                        x == "made"
                    ).sum(),  # Count made FGs
                    "kick_distance": ["max", "mean"],
                    "temp": "first",
                    "wind": "first",
                }
            )
            .reset_index()
        )

        # Flatten column names
        weekly_stats.columns = [
            "kicker_id",
            "kicker_name",
            "team",
            "opponent",
            "game_date",
            "attempts",
            "made",
            "longest_fg",
            "avg_distance",
            "temperature",
            "wind_speed",
        ]

        return weekly_stats

    except Exception as e:
        print(f"Error fetching field goal data: {e}")
        return pd.DataFrame()


def get_current_nfl_week():
    """Estimate current NFL week based on date"""
    # NFL season typically starts first Thursday in September
    # This is a simplified calculation
    today = date.today()
    season_start = date(2024, 9, 5)  # 2024-2025 season start

    if today < season_start:
        return 1

    days_since_start = (today - season_start).days
    week = min(days_since_start // 7 + 1, 18)
    return week


def match_predictions_with_actuals(week=None, season=2025):
    """
    Match our predictions with actual results

    Args:
        week (int): NFL week number
        season (int): NFL season year
    """
    # Get actual results from nflverse
    actuals_df = get_weekly_field_goal_data(week, season)

    if actuals_df.empty:
        print("No actual field goal data found")
        return

    # Get our historical predictions from the database for the game week
    # First, try to get predictions from KickerPredictions (historical)
    # Then fallback to current Kickers table if needed

    # Calculate approximate date range for the week
    if week:
        # For historical data, look for predictions from that week
        season_start = date(season, 9, 5)  # Approximate season start
        week_start = season_start + timedelta(weeks=(week - 1))
        week_end = week_start + timedelta(days=7)

        historical_predictions = (
            db_session.query(KickerPredictions)
            .filter(
                and_(
                    KickerPredictions.game_date >= week_start,
                    KickerPredictions.game_date <= week_end,
                )
            )
            .all()
        )

        print(
            f"📅 Found {len(historical_predictions)} historical predictions for week {week}"
        )

        # Also get current predictions as fallback
        current_predictions = db_session.query(Kickers).all()
        print(f"📋 Found {len(current_predictions)} current predictions as fallback")

    else:
        # For current week, use both historical and current
        historical_predictions = db_session.query(KickerPredictions).all()
        current_predictions = db_session.query(Kickers).all()
        print(f"📅 Found {len(historical_predictions)} historical predictions total")
        print(f"📋 Found {len(current_predictions)} current predictions as fallback")

    results_processed = 0

    for _, actual in actuals_df.iterrows():
        # Try to match with our predictions
        kicker_name = actual["kicker_name"]
        game_date = pd.to_datetime(actual["game_date"]).date()

        # Find matching prediction - first try historical, then current
        prediction = None
        prediction_source = None

        def match_kicker_name(pred, kicker_name_lower):
            """Helper function to match kicker names with various formats"""
            pred_name_attr = (
                "kicker_player_name" if hasattr(pred, "kicker_player_name") else "name"
            )
            pred_name = getattr(pred, pred_name_attr, "").lower()

            # Direct match
            if pred_name == kicker_name_lower:
                return True

            # Handle abbreviated names in either direction
            # Case 1: Actual name is abbreviated (e.g., "M.Prater" vs "Matt Prater")
            if "." in kicker_name_lower:
                # Split "M.Prater" into ["M", "Prater"]
                actual_parts = kicker_name_lower.replace(".", "").split()
                if len(actual_parts) >= 2:
                    actual_initial = actual_parts[0][0]
                    actual_last = actual_parts[1]

                    # Check if prediction name starts with same initial and has same last name
                    pred_parts = pred_name.split()
                    if (
                        len(pred_parts) >= 2
                        and pred_parts[0][0] == actual_initial
                        and pred_parts[-1] == actual_last
                    ):
                        return True

            # Case 2: Prediction name is abbreviated (e.g., "M.Prater" in pred vs "Matt Prater" actual)
            if "." in pred_name:
                # Split prediction "M.Prater" into ["M", "Prater"]
                pred_parts = pred_name.replace(".", "").split()
                if len(pred_parts) >= 2:
                    pred_initial = pred_parts[0][0]
                    pred_last = pred_parts[1]

                    # Check if actual name starts with same initial and has same last name
                    actual_parts = kicker_name_lower.split()
                    if (
                        len(actual_parts) >= 2
                        and actual_parts[0][0] == pred_initial
                        and actual_parts[-1] == pred_last
                    ):
                        return True

            # Case 3: Both names are full, check first initial + last name
            pred_parts = pred_name.split()
            actual_parts = kicker_name_lower.split()
            if (
                len(pred_parts) >= 2
                and len(actual_parts) >= 2
                and pred_parts[0][0] == actual_parts[0][0]
                and pred_parts[-1] == actual_parts[-1]
            ):
                return True

            # Fallback: check if last names match
            pred_last = pred_name.split()[-1] if pred_name else ""
            actual_last = kicker_name_lower.split()[-1] if kicker_name_lower else ""
            if pred_last and actual_last and pred_last == actual_last:
                return True

            return False

        kicker_name_lower = kicker_name.lower()

        # First, try to find in historical predictions (more accurate for specific dates)
        for pred in historical_predictions:
            if match_kicker_name(pred, kicker_name_lower):
                # Additional date proximity check for historical predictions
                pred_date = (
                    pred.game_date.date()
                    if isinstance(pred.game_date, datetime)
                    else pred.game_date
                )
                date_diff = abs((pred_date - game_date).days)
                if date_diff <= 7:  # Within a week
                    prediction = pred
                    prediction_source = "historical"
                    break

        # If no historical match, try current predictions
        if not prediction:
            for pred in current_predictions:
                if match_kicker_name(pred, kicker_name_lower):
                    prediction = pred
                    prediction_source = "current"
                    break

        if not prediction:
            print(f"❌ No prediction found for kicker: {kicker_name} on {game_date}")
            continue

        print(f"✅ Found {prediction_source} prediction for {kicker_name}")

        # Check if we already have this result
        existing = (
            db_session.query(KickerActuals)
            .filter(
                and_(
                    KickerActuals.kicker_id == str(actual["kicker_id"]),
                    KickerActuals.date == game_date,
                )
            )
            .first()
        )

        if existing:
            print(f"Result already exists for {kicker_name} on {game_date}")
            continue

        # Calculate prediction accuracy
        actual_made = int(actual["made"])

        # Extract projected field goals based on prediction source
        if prediction_source == "historical":
            projected_fgs = float(prediction.predicted_fg_made)
        else:  # current prediction
            projected_fgs = float(prediction.projected_field_goals)

        # Determine if kicker hit over 1.5 made FGs (2 or more)
        hit_over_1_5 = actual_made >= 2

        # Determine if our prediction was correct
        # If we predicted >= 1.75, we were betting over 1.5
        # If we predicted < 1.25, we were betting under 1.5
        # In between is uncertain
        if projected_fgs >= 1.75:
            our_bet = "over"
            correct_prediction = hit_over_1_5
        elif projected_fgs <= 1.25:
            our_bet = "under"
            correct_prediction = not hit_over_1_5
        else:
            our_bet = "uncertain"
            correct_prediction = None

        # Calculate confidence based on distance from 1.5
        confidence = abs(projected_fgs - 1.5) / 1.5

        # Create actual result record
        kicker_actual = KickerActuals(
            date=game_date,
            kicker_id=str(actual["kicker_id"]),
            kicker_name=kicker_name,
            team_name=actual["team"],
            opponent_name=actual["opponent"],
            venue_name=f"{actual['team']} vs {actual['opponent']}",  # Simplified
            actual_field_goals_made=actual_made,
            actual_field_goals_attempted=int(actual["attempts"]),
            actual_longest_fg=(
                int(actual["longest_fg"]) if pd.notna(actual["longest_fg"]) else None
            ),
            game_temperature=(
                float(actual["temperature"])
                if pd.notna(actual["temperature"])
                else None
            ),
            game_wind_speed=(
                float(actual["wind_speed"]) if pd.notna(actual["wind_speed"]) else None
            ),
            projected_field_goals=projected_fgs,
            hit_over_1_5=hit_over_1_5,
            correct_prediction=correct_prediction,
            prediction_confidence=confidence,
        )

        db_session.add(kicker_actual)
        results_processed += 1

        print(
            f"✅ {kicker_name}: {actual_made} FGs made, predicted {projected_fgs:.1f} ({our_bet}) [{prediction_source}]"
        )
        print(
            f"   Over 1.5: {'✅' if hit_over_1_5 else '❌'}, Prediction: {'✅' if correct_prediction else '❌' if correct_prediction is not None else '❓'}"
        )

    db_session.commit()
    print(f"\n📊 Processed {results_processed} kicker results for week {week}")


def update_kicker_actuals(week=None):
    """
    Main function to update kicker actuals for a specific week

    Args:
        week (int): NFL week number, if None uses current week
    """
    if week is None:
        # Temporary fix: hardcode to week 3 for current date (Sept 21, 2025)
        # TODO: Fix the get_current_nfl_week() function calculation issue
        today = date.today()
        if today.month == 9 and today.day >= 19 and today.day <= 25:
            week = 3
            print("🏈 Using Week 3 based on current date (Sept 21, 2025)")
        else:
            week = get_current_nfl_week()
            if week is None:
                print(
                    "❌ Cannot determine current NFL week - either it's off-season or an error occurred"
                )
                print(
                    "💡 Use --week parameter to specify a specific week: python collect_kicker_actuals.py --week 3"
                )
                return

    print(f"🏈 Updating kicker actuals for NFL Week {week}")
    match_predictions_with_actuals(week, 2025)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Collect NFL kicker actual results")
    parser.add_argument("--week", type=int, help="NFL week number (1-18)")
    parser.add_argument("--season", type=int, default=2025, help="NFL season year")

    args = parser.parse_args()

    if args.week:
        update_kicker_actuals(args.week)
    else:
        update_kicker_actuals()


def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session

    init_session()
    try:
        update_kicker_actuals()
        return {"status": "ok", "task": "nfl_collect_kicker_actuals"}
    finally:
        close_session()
