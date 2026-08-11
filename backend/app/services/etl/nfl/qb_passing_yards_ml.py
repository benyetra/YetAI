"""NFL QB passing yards ML — tier heuristic baseline + optional GBM shadow (NFL-4.3)."""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - artifacts from our own private bucket
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from app.services.etl.nfl.qb_features import (
    FEATURE_NAMES,
    TIER_ONLY_FEATURE_NAMES,
    build_qb_features,
    feature_names as qb_feature_names,
    resolve_yards_baseline,
)

BaselineMode = str  # "market" | "tier"

# Promote path (Railway gate): tier residual only — prop-line features/baseline
# collapsed toward the market in ablations (2026-08-11).
PROMOTE_BASELINE_MODE: BaselineMode = "tier"
PROMOTE_FEATURE_NAMES: tuple[str, ...] = TIER_ONLY_FEATURE_NAMES

DEFAULT_HYPERPARAMS: dict[str, Any] = {
    "n_estimators": 150,
    "max_depth": 3,
    "learning_rate": 0.06,
    "subsample": 0.85,
    "random_state": 42,
    "min_samples_leaf": 8,
}

# Capacity-shrunk candidates for promote / tier-only residual.
PROMOTE_HYPERPARAM_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "name": "default",
        **DEFAULT_HYPERPARAMS,
    },
    {
        "name": "shallow",
        "n_estimators": 100,
        "max_depth": 2,
        "learning_rate": 0.05,
        "subsample": 0.75,
        "random_state": 42,
        "min_samples_leaf": 16,
    },
    {
        "name": "strong_reg",
        "n_estimators": 80,
        "max_depth": 2,
        "learning_rate": 0.04,
        "subsample": 0.70,
        "random_state": 42,
        "min_samples_leaf": 24,
    },
)

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"
S3_PREFIX = "nfl/ml_models"
MODEL_KEY = "qb_passing_yards"
TIER_VERSION = "tier-v3"

_MODEL: object | None = None
_METADATA: dict[str, Any] | None = None
_LOAD_FAILED = False
_LOCK = threading.Lock()

_TRUTHY = frozenset({"1", "true", "yes"})


def feature_names() -> list[str]:
    return qb_feature_names()


def qb_ml_enabled() -> bool:
    return os.getenv("NFL_QB_ML_ENABLED", "").strip().lower() in _TRUTHY


def _float_or(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_features_from_tier_prediction(
    prediction: Mapping[str, Any],
    *,
    season: int,
    week: int,
    is_backup: bool = False,
    context: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Build GBM features from tier prediction + optional matchup/form context."""
    tier_yards = _float_or(prediction.get("predicted_passing_yards"), 210.0)
    return build_qb_features(
        tier_yards=tier_yards,
        season=season,
        week=week,
        is_backup=is_backup,
        confidence=_float_or(prediction.get("confidence"), 0.65),
        context=context,
    )


def _model_is_residual(metadata: Mapping[str, Any] | None) -> bool:
    """True when artifact predicts residual (actual − baseline), the current default."""
    if not metadata:
        return True
    target = str(metadata.get("target") or "").lower()
    if "residual" in target:
        return True
    if target in {"actual_passing_yards", "passing_yards"}:
        return False
    # Prefer residual for unknown / new artifacts
    return bool(metadata.get("residual_target", True))


def baseline_yards_from_features(
    features: Mapping[str, float],
    *,
    baseline_mode: BaselineMode = "market",
) -> float:
    """Baseline used for residual train/predict (market blend or tier-only)."""
    tier = _float_or(features.get("tier_yards"), 210.0)
    if baseline_mode == "tier":
        return round(tier, 1)
    line = features.get("pass_yds_line")
    line_f = _float_or(line, tier) if line is not None else None
    # Prefer explicit line_minus_tier signal: non-zero ⇒ real line was present
    lmt = features.get("line_minus_tier")
    line_is_real = None
    if lmt is not None and abs(_float_or(lmt, 0.0)) > 0.5:
        line_is_real = True
    # Explicit line_is_real flag when present (prod eval sets this)
    if features.get("line_is_real") is not None:
        try:
            line_is_real = float(features.get("line_is_real")) >= 0.5
        except (TypeError, ValueError):
            pass
    return resolve_yards_baseline(
        tier_yards=tier,
        pass_yds_line=line_f,
        line_is_real=line_is_real,
    )


def predict_yards_tier(features: Mapping[str, float]) -> float:
    return round(_float_or(features.get("tier_yards"), 210.0), 1)


def _feature_vector(
    features: Mapping[str, float],
    order: list[str] | None = None,
) -> np.ndarray:
    names = order or feature_names()
    return np.array([[float(features.get(name, 0.0)) for name in names]])


def predict_yards_residual(
    model: Any,
    features: Mapping[str, float],
    *,
    feature_order: list[str] | None = None,
) -> float:
    """Raw residual prediction (actual − baseline)."""
    vec = _feature_vector(features, feature_order)
    return float(model.predict(vec)[0])


def predict_yards_ml(
    model: Any,
    features: Mapping[str, float],
    *,
    feature_order: list[str] | None = None,
    residual_target: bool = True,
    baseline_mode: BaselineMode = "market",
) -> float:
    """
    GBM yards: ``baseline + residual`` (default) or direct yards for legacy artifacts.

    Baseline is ``0.5*(tier+line)`` when a real pass-yards line is present, else tier
    (or always tier when ``baseline_mode='tier'``).
    """
    raw = predict_yards_residual(model, features, feature_order=feature_order)
    if residual_target:
        baseline = baseline_yards_from_features(features, baseline_mode=baseline_mode)
        return round(baseline + raw, 1)
    return round(float(raw), 1)


def _fill_missing_feature_columns(features_df: pd.DataFrame) -> pd.DataFrame:
    """Fill priors for missing columns (older frames / partial context)."""
    order = feature_names()
    for col in order:
        if col in features_df.columns:
            continue
        if col in ("is_home",):
            features_df[col] = 0.5
        elif col in ("rest_days",):
            features_df[col] = 7.0
        elif col in (
            "opp_pass_yds_allowed",
            "rolling_yards_l3",
            "rolling_yards_l5",
            "season_avg_yards",
            "pass_yds_line",
        ):
            features_df[col] = features_df.get("tier_yards", 220.0)
        elif col == "rolling_attempts_l3":
            features_df[col] = 34.0
        elif col == "rolling_ypa_l3":
            features_df[col] = 7.0
        elif col == "rolling_comp_pct_l3":
            features_df[col] = 0.65
        elif col == "rolling_air_yards_l3":
            features_df[col] = 7.5
        elif col == "rolling_dropbacks_l3":
            features_df[col] = 36.0
        elif col == "rolling_sack_rate_l3":
            features_df[col] = 0.07
        elif col == "opp_air_yards_allowed":
            features_df[col] = 7.5
        elif col in ("line_minus_tier", "market_residual_l3", "line_minus_rolling"):
            features_df[col] = 0.0
        elif col == "line_is_real":
            features_df[col] = 0.0
        elif col == "opp_def_epa":
            features_df[col] = 0.0
        elif col == "opp_pressure_rate":
            features_df[col] = 0.25
        elif col == "injury_risk":
            features_df[col] = 0.0
        elif col == "implied_team_total":
            features_df[col] = 22.5
        elif col == "total_line":
            features_df[col] = 45.0
        elif col == "spread_line":
            features_df[col] = 0.0
        elif col == "temperature":
            features_df[col] = 65.0
        elif col == "wind_speed":
            features_df[col] = 5.0
        elif col == "opp_cover_base":
            features_df[col] = 3.0
        elif col == "opp_man_zone":
            features_df[col] = 0.0
        elif col == "opp_scheme_pressure":
            features_df[col] = 0.5
        else:
            features_df[col] = 0.0
    return features_df


def _baselines_for_frame(
    features_df: pd.DataFrame,
    *,
    baseline_mode: BaselineMode = "market",
) -> pd.Series:
    """Baseline per row (market blend or tier-only)."""
    return features_df.apply(
        lambda row: baseline_yards_from_features(
            row.to_dict(), baseline_mode=baseline_mode
        ),
        axis=1,
    )


def _time_ordered_split_indices(
    n: int, *, test_frac: float = 0.2
) -> tuple[slice, slice]:
    """Last ``test_frac`` rows as holdout (caller must pre-sort by season/week)."""
    if n < 10:
        cut = max(1, n - 1)
    else:
        cut = max(1, min(n - 1, int(round(n * (1.0 - test_frac)))))
    return slice(0, cut), slice(cut, n)


def train_qb_yards_model(
    dataset: tuple[pd.DataFrame, pd.Series],
    *,
    hyperparams: dict[str, Any] | None = None,
    residual_target: bool = True,
    fit_full: bool = False,
    feature_order: Sequence[str] | None = None,
    baseline_mode: BaselineMode = "market",
) -> tuple[Any, dict[str, Any]]:
    """
    Train GBM on residual ``actual − baseline`` (default) or direct yards.

    Baseline is market-aware (``resolve_yards_baseline``): blend of dynamic tier
    and real pass-yards line when present, else tier alone — or always tier when
    ``baseline_mode='tier'``.

    Holdout for CV metrics is **time-ordered** (last 20% after sorting by season,
    week) — never a random shuffle. When ``fit_full=True``, that split is used
    only for metadata; the returned model is refit on all rows.
    """
    from sklearn.ensemble import GradientBoostingRegressor  # type: ignore
    from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore

    features_df, target = dataset
    if features_df.empty or len(features_df) < 30:
        raise ValueError("insufficient training rows")

    hp = {**DEFAULT_HYPERPARAMS, **(hyperparams or {})}

    order = list(feature_order) if feature_order is not None else feature_names()
    features_df = _fill_missing_feature_columns(features_df.copy())
    target = pd.Series(target).astype(float).reset_index(drop=True)
    features_df = features_df.reset_index(drop=True)

    sort_cols = [c for c in ("season", "week") if c in features_df.columns]
    if sort_cols:
        sort_order = features_df.sort_values(sort_cols, kind="mergesort").index
        features_df = features_df.loc[sort_order].reset_index(drop=True)
        target = target.loc[sort_order].reset_index(drop=True)

    # Baselines use full feature frame (needs pass_yds_line even if excluded from X)
    baselines = _baselines_for_frame(features_df, baseline_mode=baseline_mode)
    for col in order:
        if col not in features_df.columns:
            features_df[col] = 0.0
    X = features_df[list(order)]
    if residual_target:
        y = (target.astype(float) - baselines.astype(float)).astype(float)
    else:
        y = target.astype(float)

    train_sl, test_sl = _time_ordered_split_indices(len(X), test_frac=0.2)
    X_cv_train, X_cv_test = X.iloc[train_sl], X.iloc[test_sl]
    y_cv_train, y_cv_test = y.iloc[train_sl], y.iloc[test_sl]
    base_cv_train = baselines.iloc[train_sl].to_numpy()
    base_cv_test = baselines.iloc[test_sl].to_numpy()

    cv_model = GradientBoostingRegressor(**hp)
    cv_model.fit(X_cv_train, y_cv_train)
    y_pred_cv_train = cv_model.predict(X_cv_train)
    y_pred_cv_test = cv_model.predict(X_cv_test)

    # Report MAE on yards scale (baseline + residual) for residual models
    if residual_target:
        train_yards_mae = float(
            mean_absolute_error(
                y_cv_train + base_cv_train, y_pred_cv_train + base_cv_train
            )
        )
        test_yards_mae = float(
            mean_absolute_error(y_cv_test + base_cv_test, y_pred_cv_test + base_cv_test)
        )
        train_rmse = float(
            np.sqrt(
                mean_squared_error(
                    y_cv_train + base_cv_train, y_pred_cv_train + base_cv_train
                )
            )
        )
        test_rmse = float(
            np.sqrt(
                mean_squared_error(
                    y_cv_test + base_cv_test, y_pred_cv_test + base_cv_test
                )
            )
        )
        train_residual_mae = float(mean_absolute_error(y_cv_train, y_pred_cv_train))
        test_residual_mae = float(mean_absolute_error(y_cv_test, y_pred_cv_test))
    else:
        train_yards_mae = float(mean_absolute_error(y_cv_train, y_pred_cv_train))
        test_yards_mae = float(mean_absolute_error(y_cv_test, y_pred_cv_test))
        train_rmse = float(np.sqrt(mean_squared_error(y_cv_train, y_pred_cv_train)))
        test_rmse = float(np.sqrt(mean_squared_error(y_cv_test, y_pred_cv_test)))
        train_residual_mae = train_yards_mae
        test_residual_mae = test_yards_mae

    if fit_full:
        model = GradientBoostingRegressor(**hp)
        model.fit(X, y)
        n_train_final = int(len(X))
        cv_split = "time_ordered_last_20pct_then_refit_full"
    else:
        model = cv_model
        n_train_final = int(len(X_cv_train))
        cv_split = "time_ordered_last_20pct"

    baseline_label = (
        "tier_only" if baseline_mode == "tier" else "market_aware_tier_line_blend"
    )
    train_date = datetime.utcnow().strftime("%Y%m%d")
    metadata: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "target": (
            "residual_actual_minus_baseline"
            if residual_target
            else "actual_passing_yards"
        ),
        "residual_target": bool(residual_target),
        "baseline": baseline_label,
        "baseline_mode": baseline_mode,
        "fit_full": bool(fit_full),
        "cv_split": cv_split,
        "trained_at": datetime.utcnow().isoformat(),
        "train_date": train_date,
        "model_version": (
            f"gbm-qb-residual-{train_date}"
            if residual_target
            else f"gbm-qb-yards-{train_date}"
        ),
        "n_train": n_train_final,
        "n_test": int(len(X_cv_test)),
        "cv_n_train": int(len(X_cv_train)),
        "cv_n_test": int(len(X_cv_test)),
        "features": order,
        "hyperparams": hp,
        "train_mae": train_yards_mae,
        "test_mae": test_yards_mae,
        "holdout_mae": test_yards_mae,
        "train_rmse": train_rmse,
        "test_rmse": test_rmse,
        "train_residual_mae": train_residual_mae,
        "test_residual_mae": test_residual_mae,
    }
    logger.info(
        "trained %s: train_mae=%.3f test_mae=%.3f residual=%s fit_full=%s cv=time",
        MODEL_KEY,
        metadata["train_mae"],
        metadata["test_mae"],
        residual_target,
        fit_full,
    )
    return model, metadata


def train_promote_qb_yards_model(
    dataset: tuple[pd.DataFrame, pd.Series],
    *,
    residual_target: bool = True,
    feature_order: Sequence[str] | None = None,
    baseline_mode: BaselineMode | None = None,
    hyperparam_candidates: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """
    Promote-path trainer: tier-only residual + fit_full, with a small HP sweep.

    Selects the candidate with lowest inner time-ordered CV yards MAE, then
    refits on all rows with that HP set.
    """
    order = (
        list(feature_order)
        if feature_order is not None
        else list(PROMOTE_FEATURE_NAMES)
    )
    mode: BaselineMode = (
        baseline_mode if baseline_mode is not None else PROMOTE_BASELINE_MODE
    )
    candidates = list(hyperparam_candidates or PROMOTE_HYPERPARAM_CANDIDATES)

    sweep: list[dict[str, Any]] = []
    best: tuple[float, dict[str, Any], str] | None = None
    for raw in candidates:
        cand = dict(raw)
        name = str(cand.pop("name", "candidate"))
        _, cv_meta = train_qb_yards_model(
            dataset,
            residual_target=residual_target,
            fit_full=False,
            feature_order=order,
            baseline_mode=mode,
            hyperparams=cand,
        )
        cv_mae = float(cv_meta.get("holdout_mae") or cv_meta.get("test_mae") or 1e9)
        entry = {
            "name": name,
            "hyperparams": cand,
            "cv_holdout_mae": round(cv_mae, 3),
            "cv_n_train": cv_meta.get("cv_n_train", cv_meta.get("n_train")),
            "cv_n_test": cv_meta.get("cv_n_test", cv_meta.get("n_test")),
        }
        sweep.append(entry)
        if best is None or cv_mae < best[0]:
            best = (cv_mae, cand, name)

    assert best is not None
    _, best_hp, best_name = best
    model, metadata = train_qb_yards_model(
        dataset,
        residual_target=residual_target,
        fit_full=True,
        feature_order=order,
        baseline_mode=mode,
        hyperparams=best_hp,
    )
    metadata = {
        **metadata,
        "promote_path": "tier_only_residual",
        "promote_hp_selected": best_name,
        "promote_hp_sweep": sweep,
        "model_family": "residual_gbm_tier_only",
    }
    return model, metadata


def reinject_pass_yds_line(
    features: Mapping[str, float],
    *,
    ou_line: float,
) -> dict[str, float]:
    """Update feature vector after live odds attach (real prop line)."""
    feats = {str(k): float(v) for k, v in features.items()}
    tier = _float_or(feats.get("tier_yards"), 210.0)
    line = float(ou_line)
    feats["pass_yds_line"] = line
    feats["line_minus_tier"] = line - tier
    return feats


def _bundled_model_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[4] / "models" / "nfl"
    return root / f"{MODEL_KEY}.pkl", root / f"{MODEL_KEY}_metadata.json"


def _local_model_paths() -> tuple[Path, Path] | None:
    base = os.getenv("NFL_QB_MODEL_LOCAL", "").strip()
    if base:
        root = Path(base)
        return root / f"{MODEL_KEY}.pkl", root / f"{MODEL_KEY}_metadata.json"
    # Fall back to shipped backend/models/nfl artifacts (same pattern as kickers)
    model_path, meta_path = _bundled_model_paths()
    if model_path.is_file() and meta_path.is_file():
        return model_path, meta_path
    return None


def _download_artifact(s3_key: str, local_path: Path) -> None:
    import boto3

    s3 = boto3.client("s3")
    s3.download_file(S3_BUCKET, s3_key, str(local_path))


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
            local = _local_model_paths()
            if local is not None:
                model_path, meta_path = local
                if not model_path.is_file() or not meta_path.is_file():
                    raise FileNotFoundError(
                        f"NFL QB model missing under {model_path.parent}"
                    )
                with model_path.open("rb") as f:
                    _MODEL = pickle.load(f)  # nosec B301
                _METADATA = json.loads(meta_path.read_text())
            else:
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    model_local = tmp / f"{MODEL_KEY}.pkl"
                    meta_local = tmp / f"{MODEL_KEY}_metadata.json"
                    _download_artifact(f"{S3_PREFIX}/{MODEL_KEY}.pkl", model_local)
                    _download_artifact(
                        f"{S3_PREFIX}/{MODEL_KEY}_metadata.json", meta_local
                    )
                    with model_local.open("rb") as f:
                        _MODEL = pickle.load(f)  # nosec B301
                    _METADATA = json.loads(meta_local.read_text())
            return True
        except Exception as exc:
            logger.info("NFL QB yards ML model unavailable: %s", exc)
            _LOAD_FAILED = True
            return False


def model_available() -> bool:
    return _ensure_loaded()


def predict_yards_ml_loaded(features: Mapping[str, float]) -> float | None:
    if not _ensure_loaded() or _MODEL is None:
        return None
    meta = _METADATA or {}
    order = meta.get("features") or feature_names()
    residual = _model_is_residual(meta)
    baseline_mode = str(meta.get("baseline_mode") or "market")
    if baseline_mode not in {"market", "tier"}:
        baseline_mode = "market"
    return predict_yards_ml(
        _MODEL,
        features,
        feature_order=list(order),
        residual_target=residual,
        baseline_mode=baseline_mode,
    )


def resolve_qb_model_version(*, ml_loaded: bool) -> str:
    from app.services.ml_model_version import model_version_from_metadata

    if qb_ml_enabled() and ml_loaded and _METADATA:
        prefix = "gbm-qb-residual" if _model_is_residual(_METADATA) else "gbm-qb-yards"
        return model_version_from_metadata(
            _METADATA, prefix=prefix, fallback=TIER_VERSION
        )
    return TIER_VERSION


def shadow_ml_yards_from_feature_importance(feature_importance: Any) -> float | None:
    if not feature_importance or not isinstance(feature_importance, dict):
        return None
    val = feature_importance.get("ml_shadow_yards")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def enrich_qb_prediction_for_write(
    prediction: dict[str, Any],
    *,
    season: int,
    week: int,
    is_backup: bool = False,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Shadow enrich: production yards stay tier table unless ``NFL_QB_ML_ENABLED=1``.

    ``context`` carries matchup/form features (rolling yards, opp pass D, home,
    rest, implied total, weather). See ``qb_features.build_qb_features``.
    """
    feats = build_features_from_tier_prediction(
        prediction,
        season=season,
        week=week,
        is_backup=is_backup,
        context=context,
    )
    tier_yards = predict_yards_tier(feats)
    prediction = dict(prediction)
    prediction["predicted_passing_yards"] = tier_yards

    ml_yards = predict_yards_ml_loaded(feats)
    ml_loaded = ml_yards is not None

    feature_importance: dict[str, Any] = {
        "tier_yards": tier_yards,
        "prediction_method": prediction.get("prediction_method"),
        "features": {k: feats.get(k) for k in FEATURE_NAMES},
    }
    if ml_yards is not None and not qb_ml_enabled():
        feature_importance["ml_shadow_yards"] = ml_yards

    projected = tier_yards
    version = resolve_qb_model_version(ml_loaded=ml_loaded)
    method = prediction.get("prediction_method") or "tier_table"
    if qb_ml_enabled() and ml_yards is not None:
        projected = ml_yards
        method = "gbm_qb_residual" if _model_is_residual(_METADATA) else "gbm_qb_yards"

    # Prediction intervals: prefer explicit tier intervals; widen slightly for ML
    lower = prediction.get("prediction_interval_lower")
    upper = prediction.get("prediction_interval_upper")
    if lower is None or upper is None:
        half = 35.0
        lower = max(120.0, projected - half)
        upper = min(380.0, projected + half)
    elif qb_ml_enabled() and ml_yards is not None:
        # Recenter interval on ML point estimate, keep width
        width = (float(upper) - float(lower)) / 2.0
        lower = max(120.0, projected - width)
        upper = min(380.0, projected + width)

    return {
        "predicted_passing_yards": projected,
        "model_confidence": prediction.get("confidence"),
        "prediction_method": method,
        "model_version": version,
        "feature_importance": feature_importance,
        "tier_yards": tier_yards,
        "ml_shadow_yards": ml_yards,
        "feature_context": feats,
        "prediction_interval_lower": round(float(lower), 1),
        "prediction_interval_upper": round(float(upper), 1),
    }
