"""Kicker FG attempts regressor (game-level GBM + heuristic fallback)."""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - own artifacts
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MODEL_KEY = "kicker_attempts"
FEATURE_NAMES: tuple[str, ...] = (
    "implied_team_total",
    "spread",
    "rz_efficiency",
    "third_down_rate",
    "plays_per_game",
    "is_dome",
    "wind_speed",
    "temperature",
    "week",
    "season",
)

_MODEL: object | None = None
_METADATA: dict[str, Any] | None = None
_LOAD_FAILED = False
_LOCK = threading.Lock()


def feature_names() -> list[str]:
    return list(FEATURE_NAMES)


def _float_or(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_attempt_features(
    team_data: Mapping[str, Any] | None = None,
    weather_data: Mapping[str, Any] | None = None,
    *,
    season: int | None = None,
    week: int | None = None,
) -> dict[str, float]:
    team = dict(team_data or {})
    weather = dict(weather_data or {})
    venue = str(team.get("venue_type") or weather.get("roof") or "outdoor").lower()
    is_dome = 1.0 if venue in {"dome", "closed", "retractable", "indoor"} else 0.0
    if team.get("is_dome") is not None:
        is_dome = 1.0 if bool(team.get("is_dome")) else 0.0
    return {
        "implied_team_total": _float_or(team.get("implied_team_total"), 22.5),
        "spread": _float_or(team.get("spread"), 0.0),
        "rz_efficiency": _float_or(team.get("team_red_zone_efficiency"), 60.0),
        "third_down_rate": _float_or(team.get("third_down_conversion_rate"), 40.0),
        "plays_per_game": _float_or(
            team.get("plays_per_game") or team.get("pace"), 64.0
        ),
        "is_dome": is_dome,
        "wind_speed": _float_or(weather.get("wind_speed") or weather.get("wind"), 5.0),
        "temperature": _float_or(
            weather.get("temperature") or weather.get("temp"), 65.0
        ),
        "week": float(week or team.get("week") or 1),
        "season": float(season or team.get("season") or 2024),
    }


def _feature_vector(features: Mapping[str, float]) -> np.ndarray:
    return np.array([[float(features.get(name, 0.0)) for name in FEATURE_NAMES]])


def _bundled_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[4] / "models" / "nfl"
    return root / f"{MODEL_KEY}.pkl", root / f"{MODEL_KEY}_metadata.json"


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
            model_path, meta_path = _bundled_paths()
            local = os.getenv("NFL_KICKER_ATTEMPTS_MODEL_LOCAL", "").strip()
            if local:
                root = Path(local)
                model_path = root / f"{MODEL_KEY}.pkl"
                meta_path = root / f"{MODEL_KEY}_metadata.json"
            if not model_path.is_file() or not meta_path.is_file():
                raise FileNotFoundError(f"missing {model_path}")
            with model_path.open("rb") as f:
                _MODEL = pickle.load(f)  # nosec B301
            _METADATA = json.loads(meta_path.read_text())
            return True
        except Exception as exc:
            logger.info("Kicker attempts model unavailable: %s", exc)
            _LOAD_FAILED = True
            return False


def predict_attempts_ml(
    team_data: Mapping[str, Any] | None = None,
    weather_data: Mapping[str, Any] | None = None,
    *,
    season: int | None = None,
    week: int | None = None,
) -> float | None:
    if not _ensure_loaded() or _MODEL is None:
        return None
    feats = build_attempt_features(team_data, weather_data, season=season, week=week)
    raw = float(_MODEL.predict(_feature_vector(feats))[0])
    return float(min(2.8, max(1.1, raw)))


def estimate_attempts(
    team_data: Mapping[str, Any] | None = None,
    weather_data: Mapping[str, Any] | None = None,
    *,
    season: int | None = None,
    week: int | None = None,
) -> tuple[float, str]:
    """ML attempts when loaded, else heuristic. Returns (attempts, source)."""
    from app.services.etl.nfl.kicker_volume import estimate_attempts_heuristic

    ml = predict_attempts_ml(team_data, weather_data, season=season, week=week)
    if ml is not None:
        return ml, "gbm_attempts"
    return (
        estimate_attempts_heuristic(team_data, weather_data),
        "heuristic",
    )


def build_attempts_dataset_from_fg_csv(
    csv_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Aggregate field_goal_data.csv to per-(game, kicker) attempt counts."""
    path = (
        csv_path
        or Path(__file__).resolve().parents[4] / "data" / "nfl" / "field_goal_data.csv"
    )
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=list(FEATURE_NAMES)), pd.Series(dtype=float)

    group_cols = ["game_id"]
    if "kicker_player_id" in df.columns:
        group_cols.append("kicker_player_id")
    games = (
        df.groupby(group_cols, as_index=False)
        .agg(
            n_att=("is_made", "count"),
            season=("season", "first"),
            week=("week", "first"),
            temp=("temp", "mean"),
            wind=("wind", "mean"),
            roof=("roof", "first"),
            posteam=("posteam", "first"),
            home_team=("home_team", "first"),
            away_team=("away_team", "first"),
        )
        .sort_values(["season", "week", "game_id"])
    )

    rows: list[dict[str, float]] = []
    targets: list[float] = []
    for _, row in games.iterrows():
        roof = str(row.get("roof") or "").lower()
        is_dome = 1.0 if roof in {"dome", "closed", "retractable"} else 0.0
        # Proxy implied total / spread from score context unavailable → league priors
        # with mild week/season structure so the model can still learn weather/dome.
        feats = {
            "implied_team_total": 22.5,
            "spread": 0.0,
            "rz_efficiency": 60.0,
            "third_down_rate": 40.0,
            "plays_per_game": 64.0,
            "is_dome": is_dome,
            "wind_speed": _float_or(
                row.get("wind") if pd.notna(row.get("wind")) else None, 5.0
            ),
            "temperature": _float_or(
                row.get("temp") if pd.notna(row.get("temp")) else None, 65.0
            ),
            "week": float(row.get("week") or 1),
            "season": float(row.get("season") or 2024),
        }
        rows.append(feats)
        targets.append(float(row["n_att"]))
    return pd.DataFrame(rows), pd.Series(targets, name="fg_attempts")


def train_attempts_model(
    dataset: tuple[pd.DataFrame, pd.Series] | None = None,
    *,
    hyperparams: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    from sklearn.ensemble import GradientBoostingRegressor  # type: ignore
    from sklearn.metrics import mean_absolute_error, mean_squared_error  # type: ignore
    from sklearn.model_selection import train_test_split  # type: ignore

    if dataset is None:
        dataset = build_attempts_dataset_from_fg_csv()
    features_df, target = dataset
    if features_df.empty or len(features_df) < 40:
        raise ValueError("insufficient FG attempt rows")

    default_hp = {
        "n_estimators": 100,
        "max_depth": 3,
        "learning_rate": 0.08,
        "subsample": 0.9,
        "random_state": 42,
        "min_samples_leaf": 10,
    }
    hp = {**default_hp, **(hyperparams or {})}
    for col in FEATURE_NAMES:
        if col not in features_df.columns:
            features_df[col] = 0.0
    X = features_df[list(FEATURE_NAMES)]
    X = X.fillna(
        {
            "implied_team_total": 22.5,
            "spread": 0.0,
            "rz_efficiency": 60.0,
            "third_down_rate": 40.0,
            "plays_per_game": 64.0,
            "is_dome": 0.0,
            "wind_speed": 5.0,
            "temperature": 65.0,
            "week": 1.0,
            "season": 2024.0,
        }
    )
    X_train, X_test, y_train, y_test = train_test_split(
        X, target, test_size=0.2, random_state=42
    )
    model = GradientBoostingRegressor(**hp)
    model.fit(X_train, y_train)
    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)
    train_date = datetime.utcnow().strftime("%Y%m%d")
    metadata: dict[str, Any] = {
        "model_key": MODEL_KEY,
        "target": "fg_attempts",
        "trained_at": datetime.utcnow().isoformat(),
        "train_date": train_date,
        "model_version": f"gbm-kicker-attempts-{train_date}",
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "features": list(FEATURE_NAMES),
        "hyperparams": hp,
        "train_mae": float(mean_absolute_error(y_train, y_pred_train)),
        "test_mae": float(mean_absolute_error(y_test, y_pred_test)),
        "holdout_mae": float(mean_absolute_error(y_test, y_pred_test)),
        "train_rmse": float(np.sqrt(mean_squared_error(y_train, y_pred_train))),
        "test_rmse": float(np.sqrt(mean_squared_error(y_test, y_pred_test))),
        "training_source": "field_goal_data.csv",
    }
    return model, metadata


def save_attempts_model(
    model: Any,
    metadata: dict[str, Any],
    *,
    out_dir: Path | None = None,
) -> dict[str, str]:
    root = out_dir or Path(__file__).resolve().parents[4] / "models" / "nfl"
    root.mkdir(parents=True, exist_ok=True)
    model_path = root / f"{MODEL_KEY}.pkl"
    meta_path = root / f"{MODEL_KEY}_metadata.json"
    with model_path.open("wb") as f:
        pickle.dump(model, f)
    meta_path.write_text(json.dumps(metadata, indent=2, default=str))
    return {"model": str(model_path), "metadata": str(meta_path)}
