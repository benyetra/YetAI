# scripts/mlb/classification_model.py
# Calibrated over/under classifier + park factor helper

import os
import logging
from io import BytesIO

import boto3
import joblib
import numpy as np
import pandas as pd
from sqlalchemy import text
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV

from app.services.etl.mlb._db import db_session
from app.services.etl.mlb.mlb_matchup_analysis import (
    matchup_adjusted_strikeouts,
)  # OK for training features
from app.services.etl.mlb._mlb_utils import read_csv_anywhere

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------------
# Model persistence locations
# ----------------------------
MODEL_LOCAL_PATH = os.path.join(os.path.dirname(__file__), "strikeout_model.pkl")
S3_BUCKET = "yetibets"
S3_KEY = "mlb/strikeout_model.pkl"

# ----------------------------
# Park factors (venue -> park_id -> factor)
# ----------------------------
VENUE_TO_PARK_ID = {
    "ARI": "ari",
    "Arizona Diamondbacks": "ari",
    "ATL": "atl",
    "Atlanta Braves": "atl",
    "BAL": "bal",
    "Baltimore Orioles": "bal",
    "BOS": "bos",
    "Boston Red Sox": "bos",
    "CHC": "chc",
    "Chicago Cubs": "chc",
    "CWS": "cws",
    "Chicago White Sox": "cws",
    "CIN": "cin",
    "Cincinnati Reds": "cin",
    "CLE": "cle",
    "Cleveland Guardians": "cle",
    "COL": "col",
    "Colorado Rockies": "col",
    "DET": "det",
    "Detroit Tigers": "det",
    "HOU": "hou",
    "Houston Astros": "hou",
    "KC": "kc",
    "Kansas City Royals": "kc",
    "LAA": "ana",
    "Los Angeles Angels": "ana",
    "LAD": "lad",
    "Los Angeles Dodgers": "lad",
    "MIA": "mia",
    "Miami Marlins": "mia",
    "MIL": "mil",
    "Milwaukee Brewers": "mil",
    "MIN": "min",
    "Minnesota Twins": "min",
    "NYM": "nym",
    "New York Mets": "nym",
    "NYY": "nyy",
    "New York Yankees": "nyy",
    "OAK": "oak",
    "Athletics": "oak",
    "PHI": "phi",
    "Philadelphia Phillies": "phi",
    "PIT": "pit",
    "Pittsburgh Pirates": "pit",
    "SD": "sd",
    "San Diego Padres": "sd",
    "SF": "sf",
    "San Francisco Giants": "sf",
    "SEA": "sea",
    "Seattle Mariners": "sea",
    "STL": "stl",
    "St. Louis Cardinals": "stl",
    "TB": "tb",
    "Tampa Bay Rays": "tb",
    "TEX": "tex",
    "Texas Rangers": "tex",
    "TOR": "tor",
    "Toronto Blue Jays": "tor",
    "WAS": "was",
    "Washington Nationals": "was",
}

PARK_FACTORS_CSV = "s3://yetibets/mlb/park_factors.csv"
try:
    _pf_df = read_csv_anywhere(PARK_FACTORS_CSV)
    PARK_FACTOR_MAP = {row["park_id"]: row["hr_factor"] for _, row in _pf_df.iterrows()}
except Exception as e:
    logger.warning(f"Could not load park_factors.csv: {e}")
    PARK_FACTOR_MAP = {}


def get_park_factor(park_id: str, default: float = 1.0) -> float:
    return PARK_FACTOR_MAP.get(park_id, default)


def park_factor_for_venue(venue_name: str, fallback: float = 1.0) -> float:
    pid = VENUE_TO_PARK_ID.get(venue_name)
    return PARK_FACTOR_MAP.get(pid, fallback) if pid else fallback


# ----------------------------
# Data loading for training
# ----------------------------
def load_training_data() -> pd.DataFrame:
    """
    Build features from historical projections/actuals.
    """
    core_sql = """
        SELECT
            p.date,
            p.pitcher_id,
            p.projected_strikeouts,
            p.projected_innings_pitched AS proj_ip,
            p.projected_at_bats        AS proj_ab,
            p.fanduel_line             AS threshold,
            a.actual_strikeouts
        FROM pred_strikeout_projections p
        JOIN pred_strikeout_actuals    a
          ON p.date = a.date
         AND p.pitcher_id = a.pitcher_id
    """
    result = db_session.execute(text(core_sql))
    df = pd.DataFrame(result.fetchall(), columns=result.keys())

    # Try to fetch park_id from actuals; OK if missing
    try:
        park_sql = "SELECT date, pitcher_id, park_id FROM pred_strikeout_actuals"
        result_park = db_session.execute(text(park_sql))
        df_park = pd.DataFrame(result_park.fetchall(), columns=result_park.keys())
        df = df.merge(df_park, on=["date", "pitcher_id"], how="left")
    except Exception as e:
        logger.warning(f"park_id join skipped: {e}")
        df["park_id"] = None

    # park factor
    df["park_factor"] = df["park_id"].map(get_park_factor).fillna(1.0)

    # label
    df["over_label"] = (df["actual_strikeouts"] > df["threshold"]).astype(int)

    # matchup & days rest (unchanged)
    df["matchup_factor"] = df["pitcher_id"].apply(
        lambda pid: matchup_adjusted_strikeouts(pid, None)
    )
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["pitcher_id", "date"])
    df["days_rest"] = df.groupby("pitcher_id")["date"].diff().dt.days.fillna(7)

    # NEW: distance to line
    df["proj_minus_line"] = df["projected_strikeouts"] - df["threshold"]

    required = [
        "projected_strikeouts",
        "proj_ip",
        "proj_ab",
        "threshold",
        "matchup_factor",
        "days_rest",
        "park_factor",
        "proj_minus_line",  # <- NEW required
        "over_label",
    ]
    df = df.dropna(subset=required)
    return df


# ----------------------------
# Model train / load helpers
# ----------------------------
def _train_classifier(df: pd.DataFrame):
    X = df[
        [
            "projected_strikeouts",
            "proj_ip",
            "proj_ab",
            "threshold",
            "matchup_factor",
            "days_rest",
            "park_factor",
            "proj_minus_line",
        ]
    ]  # <- added
    y = df["over_label"]

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("gbc", GradientBoostingClassifier(random_state=42)),
        ]
    )
    grid = GridSearchCV(
        pipe,
        param_grid={
            "gbc__n_estimators": [100, 200, 300],
            "gbc__learning_rate": [0.05, 0.1],
            "gbc__max_depth": [3, 4],
        },
        cv=5,
        scoring="accuracy",
        n_jobs=-1,
    )
    grid.fit(X_train, y_train)
    best = grid.best_estimator_

    calib = CalibratedClassifierCV(best, cv="prefit")
    calib.fit(X_val, y_val)
    logger.info(f"Validation accuracy: {calib.score(X_val, y_val):.4f}")
    return calib


def train_and_persist() -> str:
    df = load_training_data()
    if df.empty:
        raise RuntimeError("No training data available")
    clf = _train_classifier(df)
    # Save locally
    joblib.dump(clf, MODEL_LOCAL_PATH)
    logger.info(f"Saved classifier to {MODEL_LOCAL_PATH}")
    # Optionally push to S3
    try:
        s3 = boto3.client("s3")
        with open(MODEL_LOCAL_PATH, "rb") as f:
            s3.upload_fileobj(f, S3_BUCKET, S3_KEY)
        logger.info(f"Uploaded model to s3://{S3_BUCKET}/{S3_KEY}")
    except Exception as e:
        logger.warning(f"S3 upload skipped: {e}")
    return MODEL_LOCAL_PATH


def load_classifier():
    """
    Try local first, then S3. Returns a scikit-learn estimator or None.
    """
    # local
    if os.path.exists(MODEL_LOCAL_PATH):
        try:
            logger.info(f"Loading classifier from {MODEL_LOCAL_PATH}")
            return joblib.load(MODEL_LOCAL_PATH)
        except Exception as e:
            logger.warning(f"Local load failed: {e}")

    # s3
    try:
        logger.info(f"Fetching classifier from s3://{S3_BUCKET}/{S3_KEY}")
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        body = obj["Body"].read()
        clf = joblib.load(BytesIO(body))
        # cache locally
        try:
            with open(MODEL_LOCAL_PATH, "wb") as f:
                f.write(body)
        except Exception:
            pass
        return clf
    except Exception as e:
        logger.warning(f"S3 load failed: {e}")
        return None


def get_classifier():
    """
    Public accessor used by callers; trains if missing.
    """
    clf = load_classifier()
    if clf is None:
        logger.info("No cached classifier found; training...")
        train_and_persist()
        clf = load_classifier()
    return clf


# ----------------------------
# CLI
# ----------------------------
if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--retrain", action="store_true", help="Retrain and save model")
    args = parser.parse_args()
    if args.retrain:
        try:
            path = train_and_persist()
            print(f"⚙️  Retrain complete → {path}")
        except Exception as e:
            logger.error(f"Retrain failed: {e}")
            sys.exit(1)
    else:
        clf = get_classifier()
        print("Model loaded." if clf is not None else "Model unavailable.")
