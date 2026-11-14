"""Residual model: predicts ``resid = actual - line`` from pre-game features.

Hyperparameters are fixed a priori (they were never tuned on a scored window).
P(over) is a Platt map of the predicted residual fitted on the training rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler

FIXED_ALPHA = 10.0
GBM_PARAMS = dict(
    max_depth=2,
    n_estimators=200,
    learning_rate=0.03,
    min_child_weight=30,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_lambda=5.0,
    random_state=0,
    n_jobs=1,
)


@dataclass
class ResidualModel:
    features: list
    kind: str
    medians: pd.Series
    scaler: StandardScaler | None
    estimator: object
    platt: tuple  # (a, b): p_over = sigmoid(a * pred_resid + b)
    train_start: object
    train_end: object
    n_train: int
    stat: str = ""
    version: str = field(default="")

    def _x(self, df: pd.DataFrame) -> np.ndarray:
        x = df[self.features].astype(float).fillna(self.medians)
        x = x.fillna(0.0).to_numpy()  # a feature with no training value at all
        return self.scaler.transform(x) if self.scaler is not None else x

    def predict(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """(pred_resid, p_over) as numpy arrays."""
        pred = np.asarray(self.estimator.predict(self._x(df)), dtype=float)
        a, b = self.platt
        return pred, 1.0 / (1.0 + np.exp(-(a * pred + b)))


def _make_estimator(kind: str):
    if kind == "ridge":
        return Ridge(alpha=FIXED_ALPHA)
    if kind == "gbm":
        from xgboost import XGBRegressor

        return XGBRegressor(**GBM_PARAMS)
    raise ValueError(f"unknown kind {kind!r}")


def fit(train_df: pd.DataFrame, features, kind: str = "ridge", stat: str = ""):
    """Fit on ``train_df`` (needs ``resid``, ``over``, ``date`` and the features)."""
    features = list(features)
    x = train_df[features].astype(float)
    medians = x.median().fillna(0.0)
    x = x.fillna(medians).to_numpy()
    scaler = StandardScaler().fit(x) if kind == "ridge" else None
    est = _make_estimator(kind)
    est.fit(scaler.transform(x) if scaler is not None else x, train_df["resid"])
    pred = np.asarray(est.predict(scaler.transform(x) if scaler else x), dtype=float)
    keep = train_df["over"].notna().to_numpy()
    y = train_df["over"].to_numpy()[keep]
    if keep.sum() and len(np.unique(y)) == 2:
        lr = LogisticRegression(C=1.0).fit(pred[keep].reshape(-1, 1), y)
        platt = (float(lr.coef_[0, 0]), float(lr.intercept_[0]))
    else:  # one class only: constant probability
        platt = (0.0, 0.0)
    dates = pd.to_datetime(train_df["date"])
    return ResidualModel(
        features=features,
        kind=kind,
        medians=medians,
        scaler=scaler,
        estimator=est,
        platt=platt,
        train_start=dates.min(),
        train_end=dates.max(),
        n_train=len(train_df),
        stat=stat,
        version=f"resid-{stat}-{kind}",
    )
