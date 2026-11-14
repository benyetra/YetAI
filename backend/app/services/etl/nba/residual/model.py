"""Residual model: predicts ``resid = actual - line`` from pre-game features.

Hyperparameters are fixed a priori (they were never tuned on a scored window).
P(over) is a Platt map of the predicted residual fitted on out-of-fold (time-ordered)
predictions of the training rows. ``ridge_cv`` picks its alpha by time-ordered CV on the
training rows only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge, RidgeCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FIXED_ALPHA = 10.0
CV_ALPHAS = np.logspace(0, 4, 9)
N_SPLITS = 5
MIN_OOF_ROWS = 100
KINDS = ("ridge_cv", "ridge", "gbm")
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
    scaler: StandardScaler | None  # unused: scaling lives inside ``estimator``
    estimator: object
    platt: tuple  # (a, b): p_over = sigmoid(a * pred_resid + b)
    train_start: object
    train_end: object
    n_train: int
    stat: str = ""
    version: str = field(default="")
    alpha: float | None = None  # ridge penalty used (chosen by CV for ridge_cv)

    def _x(self, df: pd.DataFrame) -> np.ndarray:
        x = df[self.features].astype(float).fillna(self.medians)
        return x.fillna(0.0).to_numpy()  # a feature with no training value at all

    def predict(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """(pred_resid, p_over) as numpy arrays."""
        pred = np.asarray(self.estimator.predict(self._x(df)), dtype=float)
        a, b = self.platt
        return pred, 1.0 / (1.0 + np.exp(-(a * pred + b)))


def _fit_est(kind: str, x: np.ndarray, y: np.ndarray):
    """Fit one estimator (scaler included) on already-imputed ``x``."""
    if kind == "ridge":
        est = make_pipeline(StandardScaler(), Ridge(alpha=FIXED_ALPHA))
    elif kind == "ridge_cv":
        est = make_pipeline(
            StandardScaler(),
            RidgeCV(
                alphas=CV_ALPHAS,
                cv=TimeSeriesSplit(n_splits=N_SPLITS),
                scoring="neg_mean_absolute_error",
            ),
        )
    elif kind == "gbm":
        from xgboost import XGBRegressor

        est = XGBRegressor(**GBM_PARAMS)
    else:
        raise ValueError(f"unknown kind {kind!r}")
    return est.fit(x, y)


def _platt(pred: np.ndarray, over: np.ndarray) -> tuple:
    keep = ~np.isnan(pred) & ~np.isnan(over)
    y = over[keep]
    if keep.sum() and len(np.unique(y)) == 2:
        lr = LogisticRegression(C=1.0).fit(pred[keep].reshape(-1, 1), y)
        return float(lr.coef_[0, 0]), float(lr.intercept_[0])
    return (0.0, 0.0)  # one class only: constant probability


def fit(train_df: pd.DataFrame, features, kind: str = "ridge_cv", stat: str = ""):
    """Fit on ``train_df`` (needs ``resid``, ``over``, ``date`` and the features)."""
    features = list(features)
    train_df = train_df.sort_values("date", kind="stable")
    x = train_df[features].astype(float)
    medians = x.median().fillna(0.0)
    # ponytail: medians use all training rows incl. OOF validation rows (features only)
    x = x.fillna(medians).to_numpy()
    y = train_df["resid"].to_numpy(dtype=float)
    over = train_df["over"].to_numpy(dtype=float)
    est = _fit_est(kind, x, y)
    # Platt on out-of-fold predictions (estimator refitted per fold); rows in no
    # validation fold get NaN and are not used.
    oof = np.full(len(x), np.nan)
    if len(x) > N_SPLITS + 1:
        for tr, va in TimeSeriesSplit(n_splits=N_SPLITS).split(x):
            oof[va] = _fit_est(kind, x[tr], y[tr]).predict(x[va])
    if (~np.isnan(oof) & ~np.isnan(over)).sum() >= MIN_OOF_ROWS:
        platt = _platt(oof, over)
    else:  # too few OOF rows: in-sample fallback
        platt = _platt(np.asarray(est.predict(x), dtype=float), over)
    dates = pd.to_datetime(train_df["date"])
    alpha = {"ridge": FIXED_ALPHA}.get(kind)
    if kind == "ridge_cv":
        alpha = float(est[-1].alpha_)
    return ResidualModel(
        features=features,
        kind=kind,
        medians=medians,
        scaler=None,
        estimator=est,
        platt=platt,
        train_start=dates.min(),
        train_end=dates.max(),
        n_train=len(train_df),
        stat=stat,
        version=f"resid-{stat}-{kind}-{dates.max():%Y%m%d}"[:64],
        alpha=alpha,
    )
