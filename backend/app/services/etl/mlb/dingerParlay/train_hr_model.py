#!/usr/bin/env python3
import argparse
import logging
from datetime import datetime
import pandas as pd
import numpy as np
import joblib
import matplotlib.pyplot as plt

from sklearn.model_selection import TimeSeriesSplit, RandomizedSearchCV
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_squared_error, r2_score

import xgboost as xgb
import lightgbm as lgb

# Optional S3 support
try:
    import boto3
    from io import BytesIO, StringIO
except ImportError:
    boto3 = None

def read_csv_any(path, **kwargs):
    """Read CSV from S3 or local."""
    if path.startswith("s3://"):
        if boto3 is None:
            raise ImportError("boto3 required for S3 support")
        bucket, key = path.split("/")[2], "/".join(path.split("/")[3:])
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        raw = obj["Body"].read()
        return pd.read_csv(BytesIO(raw), **kwargs)
    return pd.read_csv(path, **kwargs)

def save_model_any(obj, path):
    """Save joblib model to S3 or local."""
    if path.startswith("s3://"):
        bucket, key = path.split("/")[2], "/".join(path.split("/")[3:])
        buf = BytesIO()
        joblib.dump(obj, buf)
        buf.seek(0)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
        logging.info(f"Saved model to {path}")
    else:
        joblib.dump(obj, path)
        logging.info(f"Saved model to {path}")

def save_plot_any(fig, path):
    """Save matplotlib figure to S3 or local."""
    if path.startswith("s3://"):
        if boto3 is None:
            raise ImportError("boto3 required for S3 support")
        bucket, key = path.split("/")[2], "/".join(path.split("/")[3:])
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue(), ContentType='image/png')
        logging.info(f"Saved plot to {path}")
    else:
        fig.savefig(path, bbox_inches="tight")
        logging.info(f"Saved plot to {path}")

def main():
    p = argparse.ArgumentParser(
        description="Train an HR model with randomized search and hold-out eval (regressor version)"
    )
    p.add_argument('--training',    required=True, help='Path to training CSV')
    p.add_argument('--output',      required=True, help='Where to save final model .pkl')
    p.add_argument('--model-type',  choices=['xgb','lgbm'], default='xgb')
    p.add_argument('--holdout-date',required=True, help='YYYY-MM-DD hold-out split date')
    p.add_argument('--splits',      type=int, default=5, help='TimeSeriesSplit folds')
    p.add_argument('--iters',       type=int, default=50, help='RandomizedSearchCV iterations')
    p.add_argument('--seed',        type=int, default=42, help='Random seed')
    p.add_argument('--plot-path',   help='Optional path to save feature importance plot (local or s3://)')
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s: %(message)s')
    logging.info("Loading data…")
    df = read_csv_any(args.training, parse_dates=['game_date'])
    df = df.dropna(subset=['is_HR'])
    df['game_date'] = pd.to_datetime(df['game_date'])

    min_date, max_date = df['game_date'].min().date(), df['game_date'].max().date()
    logging.info(f"Data covers {min_date} → {max_date}")

    user_hold = pd.to_datetime(args.holdout_date).date()
    cutoff_date = (df['game_date'].quantile(0.8).date()
                   if user_hold >= max_date else user_hold)
    if user_hold >= max_date:
        logging.warning(f"holdout-date {user_hold} ≥ max data date; falling back to 80th percentile: {cutoff_date}")

    train_mask = df['game_date'] < pd.to_datetime(cutoff_date)
    X = df[['PowerScore','HR9','K9','hr_factor','temp','wind_speed','platoon']].astype(float)
    y = df['is_HR'].astype(float)
    X_train, y_train = X[train_mask], y[train_mask]
    X_hold,  y_hold  = X[~train_mask], y[~train_mask]
    if len(X_hold) == 0:
        raise RuntimeError(f"No hold-out rows after {cutoff_date}")
    logging.info(f"Train size: {len(X_train)}, Hold-out size: {len(X_hold)}")

    bad_cols = [col for col in X.columns if X[col].nunique() <= 1 or X[col].isna().any() or np.isinf(X[col]).any()]
    if bad_cols:
        logging.warning(f"Dropping constant or invalid feature columns: {bad_cols}")
        X = X.drop(columns=bad_cols)
        X_train = X_train.drop(columns=bad_cols)
        X_hold = X_hold.drop(columns=bad_cols)

    if args.model_type == 'xgb':
        base = xgb.XGBRegressor(objective='reg:squarederror', random_state=args.seed, n_jobs=-1, tree_method='auto')
        param_dist = {
            'clf__max_depth':        [3, 6, 9],
            'clf__learning_rate':    [0.01, 0.05, 0.1],
            'clf__n_estimators':     [100, 200, 400],
            'clf__subsample':        [0.6, 0.8, 1.0],
            'clf__colsample_bytree': [0.6, 0.8, 1.0],
        }
    else:
        base = lgb.LGBMRegressor(objective='regression', random_state=args.seed, n_jobs=-1)
        param_dist = {
            'clf__num_leaves':       [31, 64, 128],
            'clf__learning_rate':    [0.01, 0.05, 0.1],
            'clf__n_estimators':     [100, 200, 400],
            'clf__subsample':        [0.6, 0.8, 1.0],
        }

    pipe = Pipeline([
        ('scaler', StandardScaler()),
        ('clf',    base),
    ])

    tscv = TimeSeriesSplit(n_splits=args.splits)
    search = RandomizedSearchCV(
        pipe, param_dist,
        cv=tscv,
        scoring='neg_mean_squared_error',
        n_iter=args.iters,
        random_state=args.seed,
        n_jobs=-1,
        verbose=1
    )
    logging.info("Starting RandomizedSearchCV…")
    search.fit(X_train, y_train)
    best = search.best_estimator_
    logging.info(f"Best params: {search.best_params_}")

    logging.info("Evaluating on hold-out…")
    preds = best.predict(X_hold)
    rmse = np.sqrt(mean_squared_error(y_hold, preds))
    r2   = r2_score(y_hold, preds)
    logging.info(f"Hold-out RMSE: {rmse:.5f}, R²: {r2:.4f}")

    # Optional plot
    if args.plot_path:
        logging.info(f"Generating feature importance plot…")
        features = list(X_train.columns)
        importances = (
            best.named_steps['clf'].feature_importances_
            if args.model_type == 'lgbm'
            else best.named_steps['clf'].get_booster().get_score(importance_type='gain')
        )

        if args.model_type == 'xgb':
            importances = {k: importances.get(k, 0.0) for k in features}
            sorted_items = sorted(importances.items(), key=lambda x: x[1])
            labels, values = zip(*sorted_items)
        else:
            sorted_idx = np.argsort(importances)
            labels = [features[i] for i in sorted_idx]
            values = importances[sorted_idx]

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.barh(labels, values)
        ax.set_title("Feature Importance")
        ax.set_xlabel("Importance")
        ax.set_ylabel("Feature")
        fig.tight_layout()

        save_plot_any(fig, args.plot_path)
        plt.close(fig)

    save_model_any(best, args.output)
    logging.info("🎉 Done!")

if __name__ == '__main__':
    main()
