"""Isotonic / Platt calibration for game-model home-win probabilities."""

from __future__ import annotations

import logging
import os
import pickle
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

logger = logging.getLogger(__name__)

WIN_CALIBRATOR_LOCAL = os.path.join(
    os.path.dirname(__file__), "game_model_win_calibrator.pkl"
)
WIN_CALIBRATOR_S3_KEY = "mlb/game_model_win_calibrator.pkl"


def split_calibration_holdout(
    train_df: pd.DataFrame,
    val_fraction: float = 0.15,
    min_cal_rows: int = 50,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Temporal tail of training rows used only to fit probability calibrators."""
    train_df = train_df.sort_values("date").reset_index(drop=True)
    cal_n = max(min_cal_rows, int(len(train_df) * val_fraction))
    cal_n = min(cal_n, len(train_df) - 1)
    split_at = len(train_df) - cal_n
    return train_df.iloc[:split_at].copy(), train_df.iloc[split_at:].copy()


def platt_calibrate(p: np.ndarray, calibrator: LogisticRegression) -> np.ndarray:
    p = np.clip(p, 1e-6, 1.0 - 1e-6)
    logit = np.log(p / (1.0 - p)).reshape(-1, 1)
    return np.clip(calibrator.predict_proba(logit)[:, 1], 1e-6, 1.0 - 1e-6)


def fit_probability_calibrator(
    p: np.ndarray,
    y: np.ndarray,
    method: str = "auto",
) -> tuple[str, object]:
    """Fit isotonic and/or Platt; with ``auto``, pick lower Brier on this slice."""
    p = np.clip(p, 1e-6, 1.0 - 1e-6)
    y = np.asarray(y, dtype=int)
    candidates: list[tuple[str, object, float]] = []

    if method in ("isotonic", "auto"):
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(p, y)
        p_iso = np.clip(iso.predict(p), 1e-6, 1.0 - 1e-6)
        candidates.append(("isotonic", iso, float(brier_score_loss(y, p_iso))))

    if method in ("platt", "auto"):
        logit = np.log(p / (1.0 - p)).reshape(-1, 1)
        platt = LogisticRegression(C=1e10, solver="lbfgs", max_iter=500)
        platt.fit(logit, y)
        p_platt = platt_calibrate(p, platt)
        candidates.append(("platt", platt, float(brier_score_loss(y, p_platt))))

    if not candidates:
        raise ValueError(f"Unknown calibration method: {method}")
    best = min(candidates, key=lambda row: row[2])
    return best[0], best[1]


def apply_probability_calibrator(
    p: np.ndarray, method: str, calibrator: object
) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1.0 - 1e-6)
    if method == "isotonic":
        return np.clip(calibrator.predict(p), 1e-6, 1.0 - 1e-6)
    if method == "platt":
        return platt_calibrate(p, calibrator)
    raise ValueError(f"Unknown calibration method: {method}")


def calibration_table(y: np.ndarray, p: np.ndarray, n_buckets: int = 5) -> list[dict]:
    """Mean predicted vs empirical home-win rate by probability bucket."""
    p = np.clip(p, 1e-6, 1.0 - 1e-6)
    edges = np.linspace(0.0, 1.0, n_buckets + 1)
    rows = []
    for i in range(n_buckets):
        lo, hi = edges[i], edges[i + 1]
        if i == n_buckets - 1:
            mask = (p >= lo) & (p <= hi)
        else:
            mask = (p >= lo) & (p < hi)
        cnt = int(mask.sum())
        if cnt == 0:
            rows.append(
                {
                    "bucket": f"{lo:.2f}-{hi:.2f}",
                    "count": 0,
                    "mean_predicted": None,
                    "mean_actual": None,
                    "gap": None,
                }
            )
            continue
        rows.append(
            {
                "bucket": f"{lo:.2f}-{hi:.2f}",
                "count": cnt,
                "mean_predicted": float(p[mask].mean()),
                "mean_actual": float(y[mask].mean()),
                "gap": float(p[mask].mean() - y[mask].mean()),
            }
        )
    return rows


class WinProbabilityCalibrator:
    """Pickled bundle for production / backtest win-probability calibration."""

    def __init__(self):
        self.method: str | None = None
        self.calibrator: object | None = None
        self.is_fitted = False
        self.n_samples = 0
        self.brier_on_fit: float | None = None
        self.raw_brier_on_fit: float | None = None
        self.fitted_at_utc: str | None = None
        self.train_mode: str | None = None

    def fit(
        self, raw_probs: np.ndarray, labels: np.ndarray, method: str = "auto"
    ) -> WinProbabilityCalibrator:
        raw_probs = np.clip(np.asarray(raw_probs, dtype=float), 1e-6, 1.0 - 1e-6)
        labels = np.asarray(labels, dtype=int)
        self.method, self.calibrator = fit_probability_calibrator(
            raw_probs, labels, method=method
        )
        calibrated = apply_probability_calibrator(
            raw_probs, self.method, self.calibrator
        )
        self.n_samples = int(len(labels))
        self.raw_brier_on_fit = float(brier_score_loss(labels, raw_probs))
        self.brier_on_fit = float(brier_score_loss(labels, calibrated))
        self.fitted_at_utc = datetime.now(timezone.utc).isoformat()
        self.is_fitted = True
        return self

    def predict(self, raw_probs: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            return np.clip(np.asarray(raw_probs, dtype=float), 1e-6, 1.0 - 1e-6)
        return apply_probability_calibrator(raw_probs, self.method, self.calibrator)

    def predict_single(self, raw_prob: float) -> float:
        return float(self.predict(np.array([raw_prob]))[0])

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "calibrator": self.calibrator,
            "is_fitted": self.is_fitted,
            "n_samples": self.n_samples,
            "brier_on_fit": self.brier_on_fit,
            "raw_brier_on_fit": self.raw_brier_on_fit,
            "fitted_at_utc": self.fitted_at_utc,
            "train_mode": self.train_mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WinProbabilityCalibrator:
        obj = cls()
        obj.method = data.get("method")
        obj.calibrator = data.get("calibrator")
        obj.is_fitted = bool(data.get("is_fitted"))
        obj.n_samples = int(data.get("n_samples", 0))
        obj.brier_on_fit = data.get("brier_on_fit")
        obj.raw_brier_on_fit = data.get("raw_brier_on_fit")
        obj.fitted_at_utc = data.get("fitted_at_utc")
        obj.train_mode = data.get("train_mode")
        return obj


def save_win_calibrator(
    calibrator: WinProbabilityCalibrator, path: str | None = None
) -> str:
    path = path or WIN_CALIBRATOR_LOCAL
    with open(path, "wb") as fh:
        pickle.dump(calibrator.to_dict(), fh)
    logger.info(
        "Saved win calibrator (%s, n=%s, Brier fit=%.4f) to %s",
        calibrator.method,
        calibrator.n_samples,
        calibrator.brier_on_fit or 0.0,
        path,
    )
    return path


def load_win_calibrator(path: str | None = None) -> WinProbabilityCalibrator | None:
    path = path or WIN_CALIBRATOR_LOCAL
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as fh:
            data = pickle.load(fh)
        cal = WinProbabilityCalibrator.from_dict(data)
        if cal.is_fitted:
            return cal
    except Exception as exc:
        logger.warning("Failed to load win calibrator from %s: %s", path, exc)
    return None


def fit_win_calibrator_on_tail(
    train_df: pd.DataFrame,
    raw_probs: np.ndarray,
    val_fraction: float = 0.15,
    min_cal_rows: int = 50,
    method: str = "auto",
    train_mode: str = "full_train_tail_cal",
) -> WinProbabilityCalibrator | None:
    """Fit calibrator on the temporal tail of ``train_df`` using ``raw_probs`` aligned to that tail."""
    train_df = train_df.sort_values("date").reset_index(drop=True)
    _, cal_df = split_calibration_holdout(train_df, val_fraction, min_cal_rows)
    if len(cal_df) < min_cal_rows:
        logger.warning("Too few rows (%s) for win calibrator fit", len(cal_df))
        return None
    raw_probs = np.asarray(raw_probs, dtype=float)
    if len(raw_probs) != len(train_df):
        raise ValueError(
            f"raw_probs length {len(raw_probs)} != train_df length {len(train_df)}",
        )
    p_tail = raw_probs[-len(cal_df) :]
    y_tail = cal_df["home_win"].values.astype(int)
    bundle = WinProbabilityCalibrator()
    bundle.train_mode = train_mode
    bundle.fit(p_tail, y_tail, method=method)
    return bundle
