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
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV

from app.services.etl.mlb._db import db_session
from app.services.etl.mlb._mlb_utils import read_csv_anywhere
from app.services.ml import model_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------------
# Model persistence locations
# ----------------------------
MODEL_LOCAL_PATH = os.path.join(os.path.dirname(__file__), "strikeout_model.pkl")
S3_BUCKET = "yetibets"
S3_KEY = "mlb/strikeout_model.pkl"

# Serving copy: re-checked against S3 on the shared refresh interval, last good
# copy kept on failure, never read from local disk (see model_store.S3Object).
_CLF = model_store.S3Object(
    S3_KEY, lambda b: joblib.load(BytesIO(b)), bucket=S3_BUCKET
)

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
def _days_rest(df: pd.DataFrame) -> pd.Series:
    """Days since the pitcher's previous graded start, as serving computes it
    (``fetch_last_start_date``): looked up over ALL graded starts, not just the
    rows that also have a projection, and 7 when there is no previous start."""
    try:
        result = db_session.execute(
            text("SELECT date, pitcher_id FROM pred_strikeout_actuals")
        )
        starts = pd.DataFrame(result.fetchall(), columns=result.keys())
    except Exception as e:
        logger.warning(f"days_rest from all actuals skipped: {e}")
        starts = df[["date", "pitcher_id"]]
    starts = starts.assign(date=pd.to_datetime(starts["date"])).drop_duplicates()
    starts = starts.sort_values(["pitcher_id", "date"])
    starts["days_rest"] = starts.groupby("pitcher_id")["date"].diff().dt.days
    merged = df[["date", "pitcher_id"]].merge(
        starts, on=["date", "pitcher_id"], how="left"
    )
    return pd.Series(merged["days_rest"].fillna(7).to_numpy(), index=df.index)


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

    # Historical rows have no opposing batter id — neutral matchup (see matchup_adjusted_strikeouts).
    # Do not call matchup per row: that triggers StatsAPI/ProfileStore and stalls retrain for hours.
    # Serving passes the real lineup matchup factor, but it is not stored on
    # pred_strikeout_projections (only matchup_source is), so history cannot
    # reproduce it. The tree model never splits on a constant, so this is inert.
    df["matchup_factor"] = 1.0
    df["date"] = pd.to_datetime(df["date"])
    df["days_rest"] = _days_rest(df)

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
FEATURES = [
    "projected_strikeouts",
    "proj_ip",
    "proj_ab",
    "threshold",
    "matchup_factor",
    "days_rest",
    "park_factor",
    "proj_minus_line",
]


def _train_classifier(df: pd.DataFrame):
    """Chronological 60/20/20: fit on the oldest rows, calibrate on the next,
    score on the newest. Returns (calibrated model, holdout X, holdout y)."""
    df = df.sort_values("date", kind="stable")
    n = len(df)
    fit_end, cal_end = int(n * 0.6), int(n * 0.8)
    X, y = df[FEATURES], df["over_label"]
    X_train, y_train = X.iloc[:fit_end], y.iloc[:fit_end]
    X_cal, y_cal = X.iloc[fit_end:cal_end], y.iloc[fit_end:cal_end]
    X_hold, y_hold = X.iloc[cal_end:], y.iloc[cal_end:]
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
        cv=TimeSeriesSplit(n_splits=5),
        scoring="accuracy",
        n_jobs=-1,
    )
    grid.fit(X_train, y_train)
    best = grid.best_estimator_

    calib = CalibratedClassifierCV(best, cv="prefit")
    calib.fit(X_cal, y_cal)
    logger.info(
        f"Holdout accuracy: {calib.score(X_hold, y_hold):.4f} "
        f"brier: {_brier(calib, X_hold, y_hold):.4f}"
    )
    return calib, X_hold, y_hold


def _brier(clf, X, y) -> float:
    return float(brier_score_loss(y, clf.predict_proba(X)[:, 1]))


def train_and_persist() -> dict:
    """Train, then replace the live classifier only if its Brier score on the
    holdout is not worse than the live model's on the same rows. Returns the
    gated_upload result (status first_upload/uploaded/rejected_by_champion)."""
    df = load_training_data()
    if df.empty:
        raise RuntimeError("No training data available")
    clf, X_hold, y_hold = _train_classifier(df)
    buf = BytesIO()
    joblib.dump(clf, buf)
    result = model_store.gated_upload(
        S3_KEY,
        buf.getvalue(),
        candidate_metric=_brier(clf, X_hold, y_hold),
        metric_name="holdout_brier",
        score_champion=lambda live: _brier(
            joblib.load(BytesIO(live)), X_hold, y_hold
        ),
        manifest_extra={"holdout_rows": int(len(y_hold)), "rows": int(len(df))},
        version_prefix="gb",
        bucket=S3_BUCKET,
    )
    logger.info(f"Strikeout classifier upload: {result['status']}")
    return result


def load_classifier():
    """Current serving classifier from S3 (refreshed on the shared interval,
    last good copy kept on failure), or None until one has loaded."""
    return _CLF.get()


def probe_classifier_load() -> dict:
    """
    Attempt to unpickle the strikeout classifier and report health.

    Used by admin ml-ops status and ``scripts/prod_verify_strikeout_classifier.py``.
    Does not train on miss.
    """
    import sklearn

    result: dict = {
        "ok": False,
        "sklearn_version": getattr(sklearn, "__version__", None),
        "estimator_type": None,
        "error": None,
        "source": None,
    }
    # Serving reads only S3 (see _CLF), so the probe does too.
    try:
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
        clf = joblib.load(BytesIO(obj["Body"].read()))
        result["ok"] = clf is not None
        result["estimator_type"] = type(clf).__name__ if clf is not None else None
        result["source"] = "s3"
        if clf is None:
            result["error"] = "s3 object loaded as None"
        return result
    except Exception as e:
        result["error"] = f"s3: {e}"
        result["ok"] = False
        return result


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
            result = train_and_persist()
            print(f"⚙️  Retrain complete → {result['status']}")
        except Exception as e:
            logger.error(f"Retrain failed: {e}")
            sys.exit(1)
    else:
        clf = get_classifier()
        print("Model loaded." if clf is not None else "Model unavailable.")
