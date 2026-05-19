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
    GameProjections, GameActuals, BlowoutChances,
    StrikeoutProjections, StrikeoutActuals
)

from app.services.etl.mlb._db import db_session
from app.services.etl.mlb.odds_utils import american_to_break_even_prob

try:
    import boto3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

S3_BUCKET = 'yetibets'
META_MODEL_S3_KEY = 'mlb/meta_learner.pkl'
META_MODEL_LOCAL = os.path.join(os.path.dirname(__file__), 'meta_learner.pkl')

# Stacking features: outputs from Layer 1 + Layer 2 models
STACK_FEATURES = [
    'xgb_win_prob',          # Layer 2: XGBoost game model
    'blowout_run_diff',      # Layer 2: Blowout model run differential
    'home_bullpen_fatigue',  # Feature: bullpen fatigue
    'away_bullpen_fatigue',
    'market_implied_prob',   # Market: implied probability from closing line
    'edge_vs_market_ml',     # Divergence between model and market
    'park_factor',           # Environmental
    'temperature',
    'model_confidence',      # XGBoost confidence
]


def build_stacking_data(lookback_days=30):
    """Build training data for the meta-learner from recent projections + actuals.

    Joins GameProjections with GameActuals where we have both prediction and result.
    """
    cutoff = date.today() - timedelta(days=lookback_days)

    results = db_session.query(
        GameProjections, GameActuals
    ).join(
        GameActuals,
        (GameProjections.date == GameActuals.date) &
        (GameProjections.game_id == GameActuals.game_id)
    ).filter(
        GameProjections.date >= cutoff
    ).all()

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
            'xgb_win_prob': proj.xgb_win_prob or proj.home_win_prob,
            'blowout_run_diff': proj.blowout_run_diff or 0.0,
            'home_bullpen_fatigue': proj.home_bullpen_fatigue or 0.5,
            'away_bullpen_fatigue': proj.away_bullpen_fatigue or 0.5,
            'market_implied_prob': market_prob or 0.5,
            'edge_vs_market_ml': proj.edge_vs_market_ml or 0.0,
            'park_factor': proj.park_factor or 1.0,
            'temperature': proj.temperature or 72.0,
            'model_confidence': proj.model_confidence or 0.5,
            # Target
            'home_win': 1 if actual.winner == 'home' else 0,
            'total_runs': actual.total_runs,
            'date': proj.date,
        }
        rows.append(row)

    df = pd.DataFrame(rows).sort_values('date').reset_index(drop=True)
    logger.info(f"Built stacking data: {len(df)} games from last {lookback_days} days")
    return df


def train_meta_learner(df):
    """Train logistic regression stacking layer.

    Uses 30-day holdout with TimeSeriesSplit CV.
    """
    X = df[STACK_FEATURES].fillna(0).values
    y = df['home_win'].values

    tscv = TimeSeriesSplit(n_splits=3)

    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('clf', LogisticRegression(C=1.0, max_iter=500, random_state=42))
    ])

    scores = cross_val_score(pipeline, X, y, cv=tscv, scoring='neg_brier_score')
    avg_brier = -np.mean(scores)
    logger.info(f"Meta-learner CV Brier Score: {avg_brier:.4f}")

    # Fit on full data
    pipeline.fit(X, y)
    return pipeline


def save_meta_model(model):
    """Save meta-learner to local and S3."""
    with open(META_MODEL_LOCAL, 'wb') as f:
        pickle.dump(model, f)
    logger.info(f"Saved meta-learner to {META_MODEL_LOCAL}")

    if HAS_BOTO3:
        try:
            s3 = boto3.client('s3')
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
        with open(META_MODEL_LOCAL, 'rb') as f:
            return pickle.load(f)

    if HAS_BOTO3:
        try:
            s3 = boto3.client('s3')
            obj = s3.get_object(Bucket=S3_BUCKET, Key=META_MODEL_S3_KEY)
            return pickle.load(BytesIO(obj['Body'].read()))
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
        if proj.get('market_home_ml') is not None:
            market_prob = american_to_break_even_prob(proj['market_home_ml'])

        features = np.array([[
            proj.get('xgb_win_prob', proj.get('home_win_prob', 0.5)),
            proj.get('blowout_run_diff', 0.0),
            proj.get('home_bullpen_fatigue', 0.5),
            proj.get('away_bullpen_fatigue', 0.5),
            market_prob or 0.5,
            proj.get('edge_vs_market_ml', 0.0),
            proj.get('park_factor', 1.0),
            proj.get('temperature', 72.0),
            proj.get('model_confidence', 0.5),
        ]])

        stacked_prob = float(model.predict_proba(features)[0][1])
        proj['home_win_prob'] = round(stacked_prob, 4)
        proj['away_win_prob'] = round(1.0 - stacked_prob, 4)

    logger.info(f"Applied meta-learner to {len(projections)} projections")
    return projections



def main():
    parser = argparse.ArgumentParser(description='MLB Meta-Learner')
    parser.add_argument('--train', action='store_true', help='Train meta-learner on recent data')
    parser.add_argument('--lookback', type=int, default=30, help='Days of data to use')
    args = parser.parse_args()

    with app.app_context():
        if args.train:
            df = build_stacking_data(args.lookback)
            if df is None or len(df) < 30:
                logger.error("Not enough data for meta-learner training (need 30+ games)")
                return
            model = train_meta_learner(df)
            save_meta_model(model)
            logger.info("Meta-learner training complete")
        else:
            parser.print_help()


if __name__ == '__main__':
    main()
