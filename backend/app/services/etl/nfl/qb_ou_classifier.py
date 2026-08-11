"""QB pass-yards O/U classifier — P(over line) from features + market line."""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - artifacts from our private bucket / local models
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from app.services.etl.nfl.qb_features import FEATURE_NAMES, feature_names

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "nfl/ml_models"
MODEL_KEY = "qb_pass_yds_ou"
_OU_FEATURE = "ou_line"

_MODEL: object | None = None
_METADATA: dict[str, Any] | None = None
_LOAD_FAILED = False
_LOCK = threading.Lock()


def ou_feature_names() -> list[str]:
    return list(FEATURE_NAMES) + [_OU_FEATURE]


def _float_or(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_ou_feature_row(
    features: Mapping[str, float],
    ou_line: float,
    *,
    projected_yards: float | None = None,
) -> dict[str, float]:
    row = {name: _float_or(features.get(name), 0.0) for name in FEATURE_NAMES}
    row[_OU_FEATURE] = float(ou_line)
    # Prefer live/ML projected yards over tier when available (stronger edge signal).
    proj = projected_yards
    if proj is None:
        for key in ("projected_yards", "ml_shadow_yards", "predicted_passing_yards"):
            raw = features.get(key)
            if raw is None:
                continue
            try:
                proj = float(raw)
                break
            except (TypeError, ValueError):
                continue
    if proj is None:
        proj = _float_or(features.get("tier_yards"), 210.0)
    row["yards_minus_line"] = float(proj) - float(ou_line)
    return row


def ou_model_feature_order(metadata: Mapping[str, Any] | None = None) -> list[str]:
    if metadata and metadata.get("features"):
        return list(metadata["features"])
    return ou_feature_names() + ["yards_minus_line"]


def is_real_ou_line(
    *,
    ou_line: float | None,
    tier_yards: float | None = None,
    line_is_real: bool | None = None,
    min_abs_diff_from_tier: float = 0.5,
) -> bool:
    """True when the O/U line looks like a market prop (not a tier anchor)."""
    if ou_line is None:
        return False
    try:
        line = float(ou_line)
    except (TypeError, ValueError):
        return False
    if line <= 0:
        return False
    if line_is_real is not None:
        return bool(line_is_real)
    if tier_yards is None:
        return True
    try:
        tier = float(tier_yards)
    except (TypeError, ValueError):
        return True
    return abs(line - tier) > min_abs_diff_from_tier


def filter_real_ou_training_rows(
    features_df: pd.DataFrame,
    actuals: pd.Series,
    *,
    line_col: str = "ou_line",
    tier_col: str = "tier_yards",
    real_col: str | None = "line_is_real",
) -> tuple[pd.DataFrame, pd.Series]:
    """Keep rows with a real market line and a non-push actual."""
    if features_df.empty:
        return features_df.copy(), actuals.copy()
    keep: list[int] = []
    for idx in features_df.index:
        row = features_df.loc[idx]
        line = row.get(line_col)
        tier = row.get(tier_col)
        real_flag = None
        if real_col and real_col in features_df.columns:
            try:
                real_flag = bool(float(row.get(real_col) or 0.0) >= 0.5)
            except (TypeError, ValueError):
                real_flag = None
        if not is_real_ou_line(ou_line=line, tier_yards=tier, line_is_real=real_flag):
            continue
        try:
            actual = float(actuals.loc[idx])
            line_f = float(line)
        except (TypeError, ValueError, KeyError):
            continue
        if abs(actual - line_f) < 0.5:
            continue
        keep.append(idx)
    if not keep:
        return features_df.iloc[0:0].copy(), actuals.iloc[0:0].copy()
    return features_df.loc[keep].copy(), actuals.loc[keep].copy()


def train_qb_ou_classifier(
    features_df: pd.DataFrame,
    over_labels: pd.Series,
    *,
    hyperparams: dict[str, Any] | None = None,
    time_ordered: bool = True,
) -> tuple[Any, dict[str, Any]]:
    from sklearn.ensemble import GradientBoostingClassifier  # type: ignore
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss  # type: ignore
    from sklearn.model_selection import train_test_split  # type: ignore

    if features_df.empty or len(features_df) < 40:
        raise ValueError("insufficient O/U training rows")

    order = ou_model_feature_order()
    for col in order:
        if col not in features_df.columns:
            features_df[col] = 0.0
    X = features_df[order]
    y = over_labels.astype(int)
    if y.nunique() < 2:
        raise ValueError("O/U labels need both over and under classes")

    default_hp = {
        "n_estimators": 100,
        "max_depth": 3,
        "learning_rate": 0.08,
        "subsample": 0.85,
        "random_state": 42,
    }
    hp = {**default_hp, **(hyperparams or {})}

    # Prefer time-ordered holdout (last 20%) when rows are chronological.
    if time_ordered and len(X) >= 60:
        cut = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:cut], X.iloc[cut:]
        y_train, y_test = y.iloc[:cut], y.iloc[cut:]
        if y_train.nunique() < 2 or y_test.nunique() < 2:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.25, random_state=42, stratify=y
            )
    else:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )
    model = GradientBoostingClassifier(**hp)
    model.fit(X_train, y_train)
    proba_test = model.predict_proba(X_test)[:, 1]
    pred_test = (proba_test >= 0.5).astype(int)

    train_date = datetime.utcnow().strftime("%Y%m%d")
    metadata: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "target": "actual_over_ou_line",
        "trained_at": datetime.utcnow().isoformat(),
        "train_date": train_date,
        "model_version": f"gbm-qb-ou-{train_date}",
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "features": order,
        "hyperparams": hp,
        "real_line_only": True,
        "holdout_accuracy": float(accuracy_score(y_test, pred_test)),
        "holdout_brier": float(brier_score_loss(y_test, proba_test)),
        "holdout_log_loss": float(log_loss(y_test, proba_test)),
    }
    logger.info(
        "trained %s: acc=%.3f brier=%.3f",
        MODEL_KEY,
        metadata["holdout_accuracy"],
        metadata["holdout_brier"],
    )
    return model, metadata


def predict_over_probability(
    model: Any,
    features: Mapping[str, float],
    ou_line: float,
    *,
    feature_order: list[str] | None = None,
    projected_yards: float | None = None,
) -> float:
    row = build_ou_feature_row(features, ou_line, projected_yards=projected_yards)
    order = feature_order or ou_model_feature_order()
    vec = np.array([[float(row.get(name, 0.0)) for name in order]])
    if hasattr(model, "predict_proba"):
        return float(model.predict_proba(vec)[0, 1])
    return float(model.predict(vec)[0])


def _bundled_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[4] / "models" / "nfl"
    return root / f"{MODEL_KEY}.pkl", root / f"{MODEL_KEY}_metadata.json"


def _local_paths() -> tuple[Path, Path] | None:
    base = os.getenv("NFL_QB_MODEL_LOCAL", "").strip()
    if base:
        root = Path(base)
        return root / f"{MODEL_KEY}.pkl", root / f"{MODEL_KEY}_metadata.json"
    model_path, meta_path = _bundled_paths()
    if model_path.is_file() and meta_path.is_file():
        return model_path, meta_path
    return None


def _ensure_loaded() -> bool:
    global _MODEL, _METADATA, _LOAD_FAILED
    if _MODEL is not None and _METADATA is not None:
        return True
    if _LOAD_FAILED:
        return False
    with _LOCK:
        if _MODEL is not None and _METADATA is not None:
            return True
        if _LOAD_FAILED:
            return False
        try:
            local = _local_paths()
            if local is not None:
                model_path, meta_path = local
                if not model_path.is_file() or not meta_path.is_file():
                    raise FileNotFoundError(str(model_path))
                with model_path.open("rb") as f:
                    _MODEL = pickle.load(f)  # nosec B301
                _METADATA = json.loads(meta_path.read_text())
            else:
                import boto3

                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    model_local = tmp / f"{MODEL_KEY}.pkl"
                    meta_local = tmp / f"{MODEL_KEY}_metadata.json"
                    s3 = boto3.client("s3")
                    s3.download_file(
                        S3_BUCKET, f"{S3_PREFIX}/{MODEL_KEY}.pkl", str(model_local)
                    )
                    s3.download_file(
                        S3_BUCKET,
                        f"{S3_PREFIX}/{MODEL_KEY}_metadata.json",
                        str(meta_local),
                    )
                    with model_local.open("rb") as f:
                        _MODEL = pickle.load(f)  # nosec B301
                    _METADATA = json.loads(meta_local.read_text())
            return True
        except Exception as exc:
            logger.info("NFL QB O/U classifier unavailable: %s", exc)
            _LOAD_FAILED = True
            return False


def predict_over_probability_loaded(
    features: Mapping[str, float],
    ou_line: float,
    *,
    projected_yards: float | None = None,
) -> float | None:
    if not _ensure_loaded() or _MODEL is None:
        return None
    order = ou_model_feature_order(_METADATA)
    return predict_over_probability(
        _MODEL,
        features,
        ou_line,
        feature_order=order,
        projected_yards=projected_yards,
    )


# Default ML edge vs 0.5 — tightened vs prior 8% to cut coin-flip O/U calls.
DEFAULT_OU_MIN_EDGE = 0.10


def recommendation_from_over_prob(
    over_prob: float,
    *,
    min_edge: float = DEFAULT_OU_MIN_EDGE,
) -> dict[str, Any]:
    """Map P(over) to OVER/UNDER/PASS with edge vs 0.5."""
    edge = over_prob - 0.5
    if abs(edge) < min_edge:
        return {
            "recommendation": "PASS",
            "reason": f"ML O/U edge too small (|{edge:.1%}| < {min_edge:.0%})",
            "over_probability": round(over_prob, 3),
            "edge_probability": round(edge, 3),
        }
    if edge > 0:
        return {
            "recommendation": "OVER",
            "reason": f"ML P(over)={over_prob:.1%}",
            "over_probability": round(over_prob, 3),
            "edge_probability": round(edge, 3),
        }
    return {
        "recommendation": "UNDER",
        "reason": f"ML P(over)={over_prob:.1%}",
        "over_probability": round(over_prob, 3),
        "edge_probability": round(edge, 3),
    }


# Silence unused import warning for feature_names re-export convenience
_ = feature_names
