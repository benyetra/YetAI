import os
import sys
import pandas as pd
import numpy as np
import requests
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler, PolynomialFeatures, MinMaxScaler
from sklearn.pipeline import make_pipeline
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import GradientBoostingRegressor
import logging
from app.services.etl.mlb._db import db_session
from sqlalchemy.exc import SQLAlchemyError

from datetime import datetime
from app.services.etl.mlb.mlb_matchup_analysis import matchup_adjusted_strikeouts
from app.services.etl.mlb.mlb_pitcher_analysis import fetch_pitcher_data
from app.services.etl.mlb.mlb_batter_analysis import fetch_batter_performance_vs_pitches
from sqlalchemy import text

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables

# Initialize Flask app


def fetch_past_performance_metrics(pitcher_id):
    """
    Fetches past performance metrics for a pitcher.
    """
    try:
        query = text(
            """
            SELECT
                projections.date,
                projections.projected_strikeouts,
                actuals.actual_strikeouts,
                projections.projected_innings_pitched,
                actuals.actual_innings_pitched,
                projections.projected_at_bats,
                actuals.actual_at_bats,
                ABS(projections.projected_strikeouts - actuals.actual_strikeouts) AS strikeout_error,
                ABS(projections.projected_innings_pitched - actuals.actual_innings_pitched) AS innings_error,
                ABS(projections.projected_at_bats - actuals.actual_at_bats) AS at_bats_error
            FROM pred_strikeout_projections AS projections
            JOIN pred_strikeout_actuals AS actuals
              ON projections.date = actuals.date
             AND projections.pitcher_id = actuals.pitcher_id
            WHERE projections.pitcher_id = :pitcher_id
            """
        )
        result = db_session.execute(query, {"pitcher_id": str(pitcher_id)})
        df = pd.DataFrame(result.fetchall(), columns=result.keys())

        if df.empty:
            logger.warning("No data found for pitcher %s", pitcher_id)
            return None
        return df
    except SQLAlchemyError as e:
        logger.error("Database error fetching past performance for pitcher %s: %s", pitcher_id, e)
        return None


def calculate_performance_metrics(df):
    """
    Calculates mean absolute error for past projections.
    """
    if df is None or df.empty:
        return 0.0, 0.0, 0.0

    return df['strikeout_error'].mean(), df['innings_error'].mean(), df['at_bats_error'].mean()


from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingRegressor
import numpy as np
import pandas as pd

from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingRegressor
import numpy as np
import pandas as pd

def project_at_bats_faced(pitcher_id, recent_data, projected_innings, mean_absolute_at_bats_error):
    """
    Predicts number of at-bats a pitcher will face using regression, incorporating projected innings.
    Ensures the projected at-bats are within a realistic range.
    """
    try:
        query = text(
            """
            SELECT date, innings_pitched, at_bats, strikeouts, walks, whip,
                   "baseOnBalls", "numberOfPitches"
            FROM pred_historical_pitcher_stats
            WHERE player_id = :pitcher_id
            """
        )
        result = db_session.execute(query, {"pitcher_id": str(pitcher_id)})
        df = pd.DataFrame(result.fetchall(), columns=result.keys())

        if df.empty:
            logger.warning(f"No data found for pitcher {pitcher_id}")
            return None

        # Prevent division by zero
            df['k_per_inning'] = np.where(df['innings_pitched'] > 0, df['strikeouts'] / df['innings_pitched'], 0)
            df['bb_per_inning'] = np.where(df['innings_pitched'] > 0, df['walks'] / df['innings_pitched'], 0)

            # Add projected innings as an additional feature
            df['projected_innings'] = df['innings_pitched']  # Initially set to past values

            # New: Factor in opposing team’s discipline (walk rate, chase rate)
            df['discipline_factor'] = (df['walks'] + df['baseOnBalls']) / np.maximum(df['at_bats'], 1)

            X = df[['innings_pitched', 'projected_innings', 'k_per_inning', 'bb_per_inning', 'whip', 'discipline_factor', 'numberOfPitches']]
            y = df['at_bats']

            if len(df) < 5:
                logger.warning(f"Not enough data to train model for pitcher {pitcher_id}")
                return None

            # Use StandardScaler for stable regression
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            # Use a robust regression model
            model = GradientBoostingRegressor(n_estimators=150, learning_rate=0.1, max_depth=4)
            model.fit(X_scaled, y)

            # Prepare recent game data
            recent_innings = recent_data['innings_pitched']
            recent_k_per_inning = recent_data['strikeouts'] / recent_innings if recent_innings > 0 else 0
            recent_bb_per_inning = recent_data['walks'] / recent_innings if recent_innings > 0 else 0

            # Use projected innings instead of past innings
            X_recent = pd.DataFrame([[recent_innings, projected_innings, recent_k_per_inning, recent_bb_per_inning, 0, 0, 0]], 
                                    columns=X.columns)
            X_recent_scaled = scaler.transform(X_recent)

            projected_at_bats = model.predict(X_recent_scaled)[0]

            # Adjust based on projected innings: Multiply by a dynamic factor
            projected_at_bats = projected_at_bats * (projected_innings / max(1, recent_innings))

            # Apply a confidence adjustment instead of absolute error subtraction
            confidence_adjustment = mean_absolute_at_bats_error * 0.35  # Less aggressive error impact
            projected_at_bats = projected_at_bats + confidence_adjustment

            # Use realistic min/max values for at-bats (based on MLB averages)
            projected_at_bats = max(17, min(40, projected_at_bats))

            logger.info(f"Final projected at-bats for pitcher {pitcher_id}: {projected_at_bats}")
            return round(projected_at_bats, 2)

    except Exception as e:
        logger.error(f"Error in projecting at-bats faced for pitcher {pitcher_id}: {e}")
        return None
    
def project_innings_pitched(pitcher_data, mean_absolute_innings_error):
    """
    Predicts innings pitched using weighted regression.
    """
    try:
        k_per_9_weight = 0.05
        last_5_avg_k_per_9_weight = 0.05
        combined_score_weight = 0.05
        avg_innings_weight = 0.45
        error_weight = 0.1  # New weight for historical error

        innings_pitched = pitcher_data.get('innings_pitched', 0.0)
        avg_innings_pitched = innings_pitched / max(pitcher_data.get('games_played', 1), 1)

        projected_innings_pitched = (
            k_per_9_weight * pitcher_data.get('k_per_9', 0.0) +
            last_5_avg_k_per_9_weight * pitcher_data.get('last_5_avg_k_per_9', 0.0) +
            combined_score_weight * pitcher_data.get('combined_score', 0.0) +
            avg_innings_weight * avg_innings_pitched +
            error_weight * mean_absolute_innings_error
        )

        return round(min(max(projected_innings_pitched, 1.0), 9.0), 2)
    except Exception as e:
        logger.error(f"Error in projecting innings pitched: {e}")
        return 0.0


from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

def perform_regression_analysis(pitcher_id, batter_id, innings_pitched, at_bats):
    """
    Predicts strikeouts for a pitcher using regression, adjusted for matchup factors.
    """
    try:
        matchup_k_factor = matchup_adjusted_strikeouts(pitcher_id, batter_id)

        past_performance_df = fetch_past_performance_metrics(pitcher_id)

        if past_performance_df is not None and not past_performance_df.empty:
            mean_absolute_error = calculate_performance_metrics(past_performance_df)[0]
        else:
            mean_absolute_error = 0.0

        query = text(
            """
            SELECT player_id, date, at_bats, innings_pitched, strikeouts, walks, whip,
                   "baseOnBalls", "numberOfPitches", season
            FROM pred_historical_pitcher_stats
            WHERE player_id = :pitcher_id
            """
        )
        result = db_session.execute(query, {"pitcher_id": str(pitcher_id)})
        df = pd.DataFrame(result.fetchall(), columns=result.keys())

        if df.empty:
            logger.warning("No data found for pitcher %s", pitcher_id)
            return None

        X = df[
            [
                "at_bats",
                "innings_pitched",
                "walks",
                "whip",
                "baseOnBalls",
                "numberOfPitches",
            ]
        ]
        y = df["strikeouts"]

        if len(df) < 5:
            logger.warning("Not enough data to train model for pitcher %s", pitcher_id)
            return None

        model = make_pipeline(
            StandardScaler(),
            PolynomialFeatures(degree=3, include_bias=False),
            GradientBoostingRegressor(
                n_estimators=120, learning_rate=0.08, max_depth=3
            ),
        )
        model.fit(X, y)

        today_data = pd.DataFrame(
            [[at_bats, innings_pitched, 0, 0, 0, 0]], columns=X.columns
        )
        projected_strikeouts = model.predict(today_data)[0]
        adjusted_strikeouts = (
            projected_strikeouts + matchup_k_factor - (mean_absolute_error * 0.3)
        )
        return round(max(0, adjusted_strikeouts), 2)
    except Exception as e:
        logger.error("Error in regression analysis for pitcher %s: %s", pitcher_id, e)
        return None

# ✅ Example Usage
if __name__ == "__main__":
    pitcher_id = '669467'  # Example pitcher_id
    batter_id = '545361'   # Example batter_id
    innings_pitched = 5.0  # Example innings pitched
    at_bats = 20           # Example at-bats faced

    # ✅ Get projected strikeouts
    projected_strikeouts = perform_regression_analysis(pitcher_id, batter_id, innings_pitched, at_bats)

    logger.info(f"Final Projected Strikeouts: {projected_strikeouts}")
