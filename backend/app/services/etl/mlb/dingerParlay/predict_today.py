#!/usr/bin/env python3
import argparse
import logging
import sys
import pandas as pd
import joblib
import boto3
from io import BytesIO
from datetime import date

from app.models.predictions_models import DailyHRPredictions

# suppress sklearn warnings
import warnings
warnings.filterwarnings('ignore', category=UserWarning)

# ----------- Utility Functions -----------

def read_csv_any(path, **kwargs):
    """Read CSV from S3 or local with pandas."""
    if path.startswith('s3://'):
        bucket, key = path.split('/')[2], '/'.join(path.split('/')[3:])
        s3 = boto3.client('s3')
        try:
            raw = s3.get_object(Bucket=bucket, Key=key)['Body'].read()
        except Exception as e:
            logging.error(f"Error reading {path}: {e}")
            sys.exit(1)
        return pd.read_csv(BytesIO(raw), **kwargs)
    else:
        return pd.read_csv(path, **kwargs)


def load_model(path):
    """Load joblib pipeline from S3 or local."""
    if path.startswith('s3://'):
        bucket, key = path.split('/')[2], '/'.join(path.split('/')[3:])
        s3 = boto3.client('s3')
        buf = BytesIO(s3.get_object(Bucket=bucket, Key=key)['Body'].read())
        return joblib.load(buf)
    else:
        return joblib.load(path)


def extract_feature_names(model):
    """
    Locate the StandardScaler step in a pipeline or calibrated model
    and return its feature_names_in_.
    """
    # direct pipeline
    if hasattr(model, 'named_steps'):
        return model.named_steps['scaler'].feature_names_in_
    # calibrated wrapper
    if hasattr(model, 'calibrated_classifiers_'):
        for clf in model.calibrated_classifiers_:
            if hasattr(clf, 'named_steps'):
                return clf.named_steps['scaler'].feature_names_in_
            base = getattr(clf, 'estimator', None) or getattr(clf, 'base_estimator', None)
            if base is not None and hasattr(base, 'named_steps'):
                return base.named_steps['scaler'].feature_names_in_
    raise RuntimeError("Cannot locate underlying pipeline in loaded model.")


def predict_and_store(daily_csv, lineup_csv, model_pkl, top_n):
    # 1) load daily_features
    logging.info(f"Loading daily features from {daily_csv}")
    df = read_csv_any(daily_csv, parse_dates=['game_date'])

    # 2) load lineup names to merge
    logging.info(f"Loading lineup for names from {lineup_csv}")
    lineup = read_csv_any(lineup_csv, parse_dates=['game_date'])
    names = lineup[['batter_id','batter_name','pitcher_id','pitcher_name']].drop_duplicates()
    df = df.merge(names, on=['batter_id','pitcher_id'], how='left')

    # 3) load pipeline
    logging.info(f"Loading model pipeline from {model_pkl}")
    model = load_model(model_pkl)

    # 4) extract feature names
    feats = extract_feature_names(model)
    missing = set(feats) - set(df.columns)
    if missing:
        logging.error(f"Missing features in daily_features: {missing}")
        sys.exit(1)

    # 5) predict — classifier or regressor
    X = df[list(feats)].astype(float)
    try:
        df['p_HR'] = model.predict(X)
    except AttributeError as e:
        logging.error(f"Model prediction failed: {e}")
        sys.exit(1)

    else:
        # regression pipeline: direct prediction
        df['p_HR'] = model.predict(X)
    df['p_HR'] = df['p_HR'].round(2)

    # 6) select top_n
    out = (
        df.sort_values('p_HR', ascending=False)
          .drop_duplicates(subset=['batter_id','pitcher_id','park_id'])
          .head(top_n)[['batter_id','batter_name','pitcher_name','park_id','p_HR']]
    )

    # 7) store into Postgres
    from app.services.etl.mlb._db import db_session

    today = date.today()
    db_session.query(DailyHRPredictions).filter(DailyHRPredictions.date == today).delete()
    db_session.commit()
    for row in out.itertuples(index=False):
        db_session.add(
            DailyHRPredictions(
                date=today,
                batter_id=row.batter_id,
                batter_name=row.batter_name,
                pitcher_name=row.pitcher_name,
                park_id=row.park_id,
                predicted_prob=row.p_HR,
            )
        )
    db_session.commit()
    logging.info("Stored %s HR predictions for %s", len(out), today)


def main():
    parser = argparse.ArgumentParser(description="Load daily features, predict HR, and store top-n")
    parser.add_argument('--daily', required=True, help='daily_features.csv path')
    parser.add_argument('--lineup', required=True, help='lineup CSV path for names')
    parser.add_argument('--model', required=True, help='trained model.pkl path')
    parser.add_argument('--top', type=int, default=10, help='number of top probabilities to store')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
    predict_and_store(args.daily, args.lineup, args.model, args.top)

if __name__ == '__main__':
    main()


