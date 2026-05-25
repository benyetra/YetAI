"""MLB Meta-Learner Stacking Ensemble.

Combines Layer 1 player-prop outputs (K, hits, HR) with Layer 2 game-level outputs
(XGBoost, blowout) into a final prediction via logistic regression stacking.

PRD v2.0 §6.1 Layer 3 — Meta-Learner (Stacking).
Phase 2 implementation.
"""

import sys
import os

import argparse
import logging
import pickle
from datetime import date, timedelta
from io import BytesIO

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit, cross_val_score

from app.models.predictions_models import (
    GameProjections,
    GameActuals,
    BlowoutChances,
    StrikeoutProjections,
    StrikeoutActuals,
)

from app.services.etl.mlb._db import db_session
from app.services.etl.mlb.odds_utils import american_to_break_even_prob

try:
    import boto3

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
META_MODEL_S3_KEY = "mlb/meta_learner.pkl"
META_MODEL_LOCAL = os.path.join(os.path.dirname(__file__), "meta_learner.pkl")

# Stacking features: outputs from Layer 1 + Layer 2 models
STACK_FEATURES = [
    "xgb_win_prob",  # Layer 2: XGBoost game model
    "blowout_run_diff",  # Layer 2: Blowout model run differential
    "home_bullpen_fatigue",  # Feature: bullpen fatigue
    "away_bullpen_fatigue",
    "market_implied_prob",  # Market: implied probability from closing line
    "edge_vs_market_ml",  # Divergence between model and market
    "park_factor",  # Environmental
    "temperature",
    "model_confidence",  # XGBoost confidence
]


def build_stacking_data(lookback_days=30):
    """Build training data for the meta-learner from recent projections + actuals.

    Joins GameProjections with GameActuals where we have both prediction and result.
    """
    cutoff = date.today() - timedelta(days=lookback_days)

    results = (
        db_session.query(GameProjections, GameActuals)
        .join(
            GameActuals,
            (GameProjections.date == GameActuals.date)
            & (GameProjections.game_id == GameActuals.game_id),
        )
        .filter(GameProjections.date >= cutoff)
        .all()
    )

    if not results:
        logger.warning("No projection-actual pairs found for stacking data")
        return None

    rows = []
    for proj, actual in results:
        # Compute market implied probability
        market_prob = None
        if proj.market_home_ml is not None:
            market_prob = american_to_break_even_prob(proj.market_home_ml)

        row = {
            "xgb_win_prob": proj.xgb_win_prob or proj.home_win_prob,
            "blowout_run_diff": proj.blowout_run_diff or 0.0,
            "home_bullpen_fatigue": proj.home_bullpen_fatigue or 0.5,
            "away_bullpen_fatigue": proj.away_bullpen_fatigue or 0.5,
            "market_implied_prob": market_prob or 0.5,
            "edge_vs_market_ml": proj.edge_vs_market_ml or 0.0,
            "park_factor": proj.park_factor or 1.0,
            "temperature": proj.temperature or 72.0,
            "model_confidence": proj.model_confidence or 0.5,
            # Target
            "home_win": 1 if actual.winner == "home" else 0,
            "total_runs": actual.total_runs,
            "date": proj.date,
        }
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    logger.info(f"Built stacking data: {len(df)} games from last {lookback_days} days")
    return df


def train_meta_learner(df):
    """Train logistic regression stacking layer.

    Uses 30-day holdout with TimeSeriesSplit CV.
    """
    X = df[STACK_FEATURES].fillna(0).values
    y = df["home_win"].values

    tscv = TimeSeriesSplit(n_splits=3)

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=1.0, max_iter=500, random_state=42)),
        ]
    )

    scores = cross_val_score(pipeline, X, y, cv=tscv, scoring="neg_brier_score")
    avg_brier = -np.mean(scores)
    logger.info(f"Meta-learner CV Brier Score: {avg_brier:.4f}")

    # Fit on full data
    pipeline.fit(X, y)
    return pipeline


def save_meta_model(model):
    """Save meta-learner to local and S3."""
    with open(META_MODEL_LOCAL, "wb") as f:
        pickle.dump(model, f)
    logger.info(f"Saved meta-learner to {META_MODEL_LOCAL}")

    if HAS_BOTO3:
        try:
            s3 = boto3.client("s3")
            buf = BytesIO()
            pickle.dump(model, buf)
            buf.seek(0)
            s3.put_object(Bucket=S3_BUCKET, Key=META_MODEL_S3_KEY, Body=buf.read())
            logger.info(f"Saved meta-learner to s3://{S3_BUCKET}/{META_MODEL_S3_KEY}")
        except Exception as e:
            logger.warning(f"Failed to save to S3: {e}")


def load_meta_model():
    """Load meta-learner from local or S3."""
    if os.path.exists(META_MODEL_LOCAL):
        with open(META_MODEL_LOCAL, "rb") as f:
            return pickle.load(f)

    if HAS_BOTO3:
        try:
            s3 = boto3.client("s3")
            obj = s3.get_object(Bucket=S3_BUCKET, Key=META_MODEL_S3_KEY)
            return pickle.load(BytesIO(obj["Body"].read()))
        except Exception:
            pass

    return None


def apply_meta_learner(projections):
    """Apply trained meta-learner to update game projections with stacked predictions.

    If no trained meta-learner exists, projections are returned unchanged.
    """
    model = load_meta_model()
    if model is None:
        logger.info("No trained meta-learner found, using base predictions")
        return projections

    for proj in projections:
        market_prob = None
        if proj.get("market_home_ml") is not None:
            market_prob = american_to_break_even_prob(proj["market_home_ml"])

        features = np.array(
            [
                [
                    proj.get("xgb_win_prob", proj.get("home_win_prob", 0.5)),
                    proj.get("blowout_run_diff", 0.0),
                    proj.get("home_bullpen_fatigue", 0.5),
                    proj.get("away_bullpen_fatigue", 0.5),
                    market_prob or 0.5,
                    proj.get("edge_vs_market_ml", 0.0),
                    proj.get("park_factor", 1.0),
                    proj.get("temperature", 72.0),
                    proj.get("model_confidence", 0.5),
                ]
            ]
        )

        stacked_prob = float(model.predict_proba(features)[0][1])
        proj["home_win_prob"] = round(stacked_prob, 4)
        proj["away_win_prob"] = round(1.0 - stacked_prob, 4)

    logger.info(f"Applied meta-learner to {len(projections)} projections")
    return projections


def run_holdout_compare(lookback_days=30, holdout_frac=0.2):
    """Train meta on early window, evaluate vs game ensemble on temporal holdout."""
    from app.services.etl.mlb.meta_learner_eval import (
        compare_meta_learner_vs_game_ensemble,
        recommend_production_use,
    )

    df = build_stacking_data(lookback_days)
    if df is None or len(df) < 30:
        logger.error("Not enough projection-actual pairs for --compare (need 30+)")
        return None

    n_holdout = max(10, int(len(df) * holdout_frac))
    if len(df) <= n_holdout + 10:
        logger.error(
            "Not enough rows for train/holdout split (need > %s games)", n_holdout + 10
        )
        return None

    train_df = df.iloc[:-n_holdout]
    holdout_df = df.iloc[-n_holdout:]
    model = train_meta_learner(train_df)

    X_h = holdout_df[STACK_FEATURES].fillna(0).values
    p_meta = model.predict_proba(X_h)[:, 1]
    p_game = holdout_df["xgb_win_prob"].fillna(0.5).values
    y_true = holdout_df["home_win"].values

    result = compare_meta_learner_vs_game_ensemble(
        {"y_true": y_true, "p_game": p_game, "p_meta": p_meta}
    )
    result["holdout_n"] = int(n_holdout)
    result["train_n"] = int(len(train_df))
    rec = recommend_production_use(result)
    logger.info(
        "Holdout compare (n=%s): game Brier=%.4f meta Brier=%.4f lift=%.4f "
        "game ML acc=%.3f meta ML acc=%.3f recommend=%s",
        result["n"],
        result["brier_game"],
        result["brier_meta"],
        result["brier_lift_game_minus_meta"],
        result["ml_accuracy_game"],
        result["ml_accuracy_meta"],
        rec,
    )
    return result


def run_evaluate_offline(scenario="meta_better"):
    """Synthetic fixture comparison without DATABASE_URL."""
    from app.services.etl.mlb.meta_learner_eval import run_offline_fixture_comparison

    result = run_offline_fixture_comparison(scenario)
    logger.info(
        "Offline fixture (%s): Brier game=%.4f meta=%.4f lift=%.4f recommend=%s",
        scenario,
        result["brier_game"],
        result["brier_meta"],
        result["brier_lift_game_minus_meta"],
        result["recommend_production_use"],
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="MLB Meta-Learner")
    parser.add_argument(
        "--train", action="store_true", help="Train meta-learner on recent data"
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Temporal holdout: meta vs game ensemble (requires DATABASE_URL)",
    )
    parser.add_argument(
        "--evaluate-offline",
        action="store_true",
        help="Synthetic fixture comparison (no DB)",
    )
    parser.add_argument(
        "--scenario",
        default="meta_better",
        choices=["meta_worse", "meta_equal", "meta_better"],
        help="Fixture scenario for --evaluate-offline",
    )
    parser.add_argument("--lookback", type=int, default=30, help="Days of data to use")
    parser.add_argument(
        "--holdout-frac",
        type=float,
        default=0.2,
        help="Fraction of stacking rows for temporal holdout (--compare)",
    )
    args = parser.parse_args()

    if args.evaluate_offline:
        run_evaluate_offline(args.scenario)
        return

    if args.compare:
        if not os.environ.get("DATABASE_URL"):
            logger.info(
                "DATABASE_URL not set; skipping --compare (use --evaluate-offline)"
            )
            return
        from app.services.etl.mlb._db import close_session, init_session

        init_session()
        try:
            run_holdout_compare(args.lookback, args.holdout_frac)
        finally:
            close_session()
        return

    if not args.train:
        parser.print_help()
        return

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL required for --train")
        return

    from app.services.etl.mlb._db import close_session, init_session

    init_session()
    try:
        df = build_stacking_data(args.lookback)
        if df is None or len(df) < 30:
            logger.error("Not enough data for meta-learner training (need 30+ games)")
            return
        model = train_meta_learner(df)
        save_meta_model(model)
        logger.info("Meta-learner training complete")
    finally:
        close_session()


if __name__ == "__main__":
    main()
