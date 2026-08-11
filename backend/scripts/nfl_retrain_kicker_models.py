"""Train / refresh NFL kicker make-miss ensemble + attempts regressor from CSV.

Usage:
  PYTHONPATH=. python scripts/nfl_retrain_kicker_models.py
  PYTHONPATH=. python scripts/nfl_retrain_kicker_models.py --skip-attempts
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (  # type: ignore
    GradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression  # type: ignore
from sklearn.metrics import accuracy_score, roc_auc_score  # type: ignore
from sklearn.model_selection import cross_val_score, train_test_split  # type: ignore
from sklearn.preprocessing import StandardScaler  # type: ignore

logger = logging.getLogger(__name__)

_MODELS_DIR = Path(__file__).resolve().parents[1] / "models" / "nfl"
_DATA_CSV = Path(__file__).resolve().parents[1] / "data" / "nfl" / "field_goal_data.csv"


def _build_make_miss_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Map field_goal_data.csv rows → MLFeatureMapper feature order."""
    from app.services.etl.nfl.ml_feature_mapping import MLFeatureMapper

    mapper = MLFeatureMapper()
    rows: list[dict[str, float]] = []
    labels: list[int] = []
    for _, row in df.iterrows():
        dist = float(row.get("kick_distance") or 40.0)
        temp = row.get("temp")
        wind = row.get("wind")
        try:
            temp_f = float(temp) if temp is not None and pd.notna(temp) else 70.0
        except (TypeError, ValueError):
            temp_f = 70.0
        try:
            wind_f = float(wind) if wind is not None and pd.notna(wind) else 5.0
        except (TypeError, ValueError):
            wind_f = 5.0
        roof = str(row.get("roof") or "outdoors").lower()
        surface = str(row.get("surface") or "grass").lower()
        venue = "dome" if roof in {"dome", "closed", "retractable"} else "outdoor"
        score_diff = float(row.get("score_differential") or 0.0)
        qtr = float(row.get("qtr") or 2.0)
        seconds = float(row.get("game_seconds_remaining") or 1800.0)
        late = int(qtr >= 4 and seconds <= 300)
        close = int(abs(score_diff) <= 7)
        is_made = int(row.get("is_made") or 0)
        kicker_data = {
            "career_fg_percentage": 85.0,
            "total_attempts": 80,
            "recent_form": 0.85,
        }
        team_data = {"venue_type": venue, "surface_type": surface}
        weather_data = {"temperature": temp_f, "wind_speed": wind_f}
        game_context = {
            "kick_distance": dist,
            "score_differential": score_diff,
            "qtr": qtr,
            "down": float(row.get("down") or 4.0),
            "ydstogo": float(row.get("ydstogo") or 5.0),
            "yardline_100": float(row.get("yardline_100") or max(1.0, dist - 17)),
            "game_seconds_remaining": seconds,
            "is_playoff": int(str(row.get("season_type") or "REG") != "REG"),
            "is_clutch": int(row.get("is_clutch") or (late and close)),
            "is_game_winning": int(row.get("is_game_winning") or 0),
        }
        df_orig, _ = mapper.prepare_prediction_features(
            kicker_data, team_data, weather_data, game_context
        )
        # Override date-derived features with game_date when present
        if "game_date" in row and pd.notna(row.get("game_date")):
            try:
                gd = pd.to_datetime(row["game_date"])
                df_orig.loc[0, "day_of_week"] = float(gd.weekday())
                df_orig.loc[0, "month"] = float(gd.month)
            except Exception:
                pass
        rows.append(df_orig.iloc[0].to_dict())
        labels.append(is_made)
    return pd.DataFrame(rows)[mapper.feature_order], pd.Series(labels, name="is_made")


def train_make_miss(df: pd.DataFrame) -> dict[str, Any]:
    X, y = _build_make_miss_frame(df)
    if len(X) < 100 or y.nunique() < 2:
        return {"status": "insufficient_data", "rows": int(len(X))}

    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    scaler = StandardScaler()
    X_train_s = np.nan_to_num(scaler.fit_transform(X_train), nan=0.0)
    X_test_s = np.nan_to_num(scaler.transform(X_test), nan=0.0)

    models: dict[str, Any] = {}
    metrics: dict[str, Any] = {}

    logistic = LogisticRegression(max_iter=500, random_state=42)
    logistic.fit(X_train_s, y_train)
    models["logistic"] = logistic

    rf = RandomForestClassifier(
        n_estimators=120, max_depth=8, random_state=42, n_jobs=-1
    )
    rf.fit(X_train, y_train)
    models["random_forest"] = rf

    gb = GradientBoostingClassifier(
        n_estimators=120, max_depth=3, learning_rate=0.08, random_state=42
    )
    gb.fit(X_train, y_train)
    models["gradient_boosting"] = gb

    try:
        from xgboost import XGBClassifier  # type: ignore

        xgb = XGBClassifier(
            n_estimators=120,
            max_depth=4,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
            eval_metric="logloss",
            use_label_encoder=False,
        )
        # Use mapped column names (no special chars) for xgboost path
        from app.services.etl.nfl.ml_feature_mapping import MLFeatureMapper

        mapper = MLFeatureMapper()
        X_train_m = X_train.rename(columns=mapper.feature_mapping)
        X_test_m = X_test.rename(columns=mapper.feature_mapping)
        xgb.fit(X_train_m, y_train)
        models["xgboost"] = xgb
    except Exception as exc:
        logger.warning("xgboost train skipped: %s", exc)
        X_test_m = None

    file_map = {
        "logistic": "logistic_model.pkl",
        "random_forest": "random_forest_model.pkl",
        "gradient_boosting": "gradient_boosting_model.pkl",
        "xgboost": "xgboost_model.pkl",
    }
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(scaler, _MODELS_DIR / "main_scaler.pkl")

    for name, model in models.items():
        if name == "logistic":
            proba = model.predict_proba(X_test_s)[:, 1]
            pred = model.predict(X_test_s)
            cv_X, cv_y = X_train_s, y_train
        elif name == "xgboost" and X_test_m is not None:
            proba = model.predict_proba(X_test_m)[:, 1]
            pred = model.predict(X_test_m)
            cv_X = X_train.rename(
                columns=__import__(
                    "app.services.etl.nfl.ml_feature_mapping",
                    fromlist=["MLFeatureMapper"],
                )
                .MLFeatureMapper()
                .feature_mapping
            )
            cv_y = y_train
        else:
            proba = model.predict_proba(X_test)[:, 1]
            pred = model.predict(X_test)
            cv_X, cv_y = X_train, y_train
        try:
            cv_scores = cross_val_score(model, cv_X, cv_y, cv=5, scoring="accuracy")
        except Exception:
            cv_scores = np.array([accuracy_score(y_test, pred)])
        metrics[name] = {
            "cv_mean": float(cv_scores.mean()),
            "cv_std": float(cv_scores.std()),
            "cv_scores": [float(s) for s in cv_scores],
            "holdout_accuracy": float(accuracy_score(y_test, pred)),
            "holdout_auc": float(roc_auc_score(y_test, proba)),
        }
        joblib.dump(model, _MODELS_DIR / file_map[name])

    metrics_path = _MODELS_DIR / "model_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    return {
        "status": "ok",
        "rows": int(len(X)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "metrics": metrics,
        "artifacts": {
            k: str(_MODELS_DIR / v) for k, v in file_map.items() if k in models
        }
        | {
            "scaler": str(_MODELS_DIR / "main_scaler.pkl"),
            "metrics": str(metrics_path),
        },
    }


def train_attempts() -> dict[str, Any]:
    from app.services.etl.nfl.kicker_attempts import (
        save_attempts_model,
        train_attempts_model,
    )

    model, metadata = train_attempts_model()
    paths = save_attempts_model(model, metadata, out_dir=_MODELS_DIR)
    return {"status": "ok", "metadata": metadata, "artifacts": paths}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-make-miss", action="store_true")
    parser.add_argument("--skip-attempts", action="store_true")
    parser.add_argument("--csv", type=str, default=str(_DATA_CSV))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    report: dict[str, Any] = {
        "trained_at": datetime.utcnow().isoformat(),
        "csv": args.csv,
    }
    if not args.skip_make_miss:
        df = pd.read_csv(args.csv)
        report["make_miss"] = train_make_miss(df)
    if not args.skip_attempts:
        report["attempts"] = train_attempts()
    out = _MODELS_DIR / "kicker_retrain_report.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    report["report_path"] = str(out)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("make_miss", {}).get("status", "ok") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
