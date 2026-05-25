"""Walk-forward evaluation and model card for ``scripts/mlb/game_model.py``.

Builds the same historical training matrix used for training, then for each
test season trains only on prior seasons and scores out-of-sample metrics
against simple baselines. Writes a JSON report under ``scripts/mlb/backtest_results/``.

Example::

    cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.mlb.game_model_eval \\
        --seasons 2023 2024 2025
    python -m app.services.etl.mlb.game_model --evaluate --compare-deferred-features \\
        --seasons 2023 2024 2025
    python -m app.services.etl.mlb.game_model --report-deferred-coverage --seasons 2024 2025
    # JSON under app/services/etl/mlb/backtest_results/
    # Deferred comparison: game_model_deferred_eval_<ts>.json (Brier, ML acc, calibration buckets)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, mean_absolute_error

from app.services.etl.mlb.win_probability_calibration import (
    apply_probability_calibrator,
    calibration_table,
    fit_probability_calibrator,
    split_calibration_holdout,
)

CAL_TRAIN_SPLIT = "split_train"
CAL_TRAIN_FULL = "full_train_tail_cal"


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "backtest_results")


def _moneyline_accuracy(y: np.ndarray, p: np.ndarray) -> float:
    pred = (p >= 0.5).astype(int)
    return float((pred == y).mean())


def _win_metrics(y_te: np.ndarray, p: np.ndarray) -> dict:
    p = np.clip(p, 1e-6, 1.0 - 1e-6)
    return {
        "win_brier": float(brier_score_loss(y_te, p)),
        "win_logloss": float(log_loss(y_te, p, labels=[0, 1])),
        "win_ml_accuracy": _moneyline_accuracy(y_te, p),
    }


def _summarize_folds(folds: list[dict]) -> tuple[dict, dict]:
    summ = {
        "mean_test_win_brier_model": float(
            np.mean([f["model"]["win_brier"] for f in folds])
        ),
        "mean_test_win_ml_accuracy_model": float(
            np.mean([f["model"]["win_ml_accuracy"] for f in folds])
        ),
        "mean_test_win_brier_calibrated": float(
            np.mean([f["model_calibrated"]["win_brier"] for f in folds])
        ),
        "mean_test_win_brier_fixed_weights": float(
            np.mean([f["model_fixed_weights"]["win_brier"] for f in folds])
        ),
        "mean_test_win_brier_baseline_0.5": float(
            np.mean([f["baselines"]["win_brier_always_0.5"] for f in folds])
        ),
        "mean_test_win_brier_baseline_train_rate": float(
            np.mean([f["baselines"]["win_brier_train_rate"] for f in folds])
        ),
        "mean_test_total_mae_model": float(
            np.mean([f["model"]["total_mae"] for f in folds])
        ),
        "mean_test_total_mae_train_mean_baseline": float(
            np.mean([f["baselines"]["total_mae_train_mean"] for f in folds])
        ),
    }
    verdict = {
        "beats_coin_flip_brier": summ["mean_test_win_brier_model"]
        < summ["mean_test_win_brier_baseline_0.5"],
        "beats_coin_flip_brier_calibrated": summ["mean_test_win_brier_calibrated"]
        < summ["mean_test_win_brier_baseline_0.5"],
        "beats_train_rate_brier": summ["mean_test_win_brier_model"]
        < summ["mean_test_win_brier_baseline_train_rate"],
        "beats_train_rate_brier_calibrated": summ["mean_test_win_brier_calibrated"]
        < summ["mean_test_win_brier_baseline_train_rate"],
        "calibration_improves_brier": summ["mean_test_win_brier_calibrated"]
        < summ["mean_test_win_brier_model"],
        "beats_train_mean_total_mae": summ["mean_test_total_mae_model"]
        < summ["mean_test_total_mae_train_mean_baseline"],
        "weight_tuning_helps_brier": summ["mean_test_win_brier_model"]
        < summ["mean_test_win_brier_fixed_weights"],
    }
    return summ, verdict


def _evaluate_holdout_fold(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    test_year: int,
    *,
    cal_train_mode: str,
    fast_train: bool,
    tune_weights: bool,
    cal_val_fraction: float,
    min_cal_rows: int,
    min_train_rows: int,
    calibration_method: str,
    train_game_models,
    ensemble_predict_proba_batch,
    ensemble_predict_value_batch,
    ensemble_with_weights,
    FEATURE_COLS,
    feature_cols=None,
) -> dict | None:
    feature_cols = feature_cols or FEATURE_COLS
    train_df = train_df.sort_values("date").reset_index(drop=True)
    _, cal_df = split_calibration_holdout(train_df, cal_val_fraction, min_cal_rows)

    if cal_train_mode == CAL_TRAIN_SPLIT:
        train_fit_df, _ = split_calibration_holdout(
            train_df, cal_val_fraction, min_cal_rows
        )
        if len(train_fit_df) < min_train_rows:
            return None
    else:
        train_fit_df = train_df

    if len(cal_df) < min_cal_rows:
        return None

    win_e, total_e = train_game_models(
        train_fit_df,
        fast=fast_train,
        tune_weights=tune_weights,
        feature_cols=feature_cols,
    )

    X_te = test_df[feature_cols].fillna(0).values
    X_cal = cal_df[feature_cols].fillna(0).values
    y_fit = train_fit_df["home_win"].values.astype(int)
    y_cal = cal_df["home_win"].values.astype(int)
    y_te = test_df["home_win"].values.astype(int)
    tot_fit = train_fit_df["total_runs"].values.astype(float)
    tot_te = test_df["total_runs"].values.astype(float)

    p_model = ensemble_predict_proba_batch(win_e, X_te)
    p_cal_raw = ensemble_predict_proba_batch(win_e, X_cal)
    t_model = ensemble_predict_value_batch(total_e, X_te)

    cal_method, calibrator = fit_probability_calibrator(
        p_cal_raw,
        y_cal,
        method=calibration_method,
    )
    p_model_calibrated = apply_probability_calibrator(p_model, cal_method, calibrator)
    cal_brier_on_fit = float(
        brier_score_loss(
            y_cal,
            apply_probability_calibrator(p_cal_raw, cal_method, calibrator),
        )
    )

    p_fixed = p_model
    if win_e.get("weights_default"):
        win_fixed = ensemble_with_weights(win_e, win_e["weights_default"])
        p_fixed = ensemble_predict_proba_batch(win_fixed, X_te)

    p_train_rate = float(np.clip(y_fit.mean(), 1e-3, 1 - 1e-3))
    p_50 = np.full_like(y_te, 0.5, dtype=float)
    p_const = np.full_like(y_te, p_train_rate, dtype=float)
    baseline_mae_mean = float(
        mean_absolute_error(tot_te, np.full_like(tot_te, tot_fit.mean()))
    )

    fold_report = {
        "test_season": int(test_year),
        "feature_columns": list(feature_cols),
        "calibration_train_mode": cal_train_mode,
        "n_train": int(len(train_fit_df)),
        "n_cal_fit": int(len(cal_df)),
        "n_test": int(len(test_df)),
        "train_home_win_rate": p_train_rate,
        "weight_tuning": {
            "win": win_e.get("weight_tuning"),
            "total": total_e.get("weight_tuning"),
            "final_win_weights": dict(win_e.get("weights", {})),
        },
        "baselines": {
            "win_brier_always_0.5": float(brier_score_loss(y_te, p_50)),
            "win_brier_train_rate": float(brier_score_loss(y_te, p_const)),
            "win_logloss_train_rate": float(log_loss(y_te, p_const, labels=[0, 1])),
            "total_mae_train_mean": baseline_mae_mean,
        },
        "model": {
            **_win_metrics(y_te, p_model),
            "total_mae": float(mean_absolute_error(tot_te, t_model)),
        },
        "model_calibrated": {
            **_win_metrics(y_te, p_model_calibrated),
        },
        "model_fixed_weights": {
            **_win_metrics(y_te, p_fixed),
        },
        "calibrator": {
            "method": cal_method,
            "brier_on_cal_fit": cal_brier_on_fit,
            "raw_brier_on_cal_fit": float(brier_score_loss(y_cal, p_cal_raw)),
        },
        "calibration_buckets_raw": calibration_table(y_te, p_model),
        "calibration_buckets_calibrated": calibration_table(y_te, p_model_calibrated),
        "calibration": calibration_table(y_te, p_model),
    }
    fold_report["deltas"] = {
        "win_brier_vs_0.5": fold_report["model"]["win_brier"]
        - fold_report["baselines"]["win_brier_always_0.5"],
        "win_brier_vs_train_rate": fold_report["model"]["win_brier"]
        - fold_report["baselines"]["win_brier_train_rate"],
        "win_brier_calibrated_vs_raw": (
            fold_report["model_calibrated"]["win_brier"]
            - fold_report["model"]["win_brier"]
        ),
        "win_brier_calibrated_vs_0.5": (
            fold_report["model_calibrated"]["win_brier"]
            - fold_report["baselines"]["win_brier_always_0.5"]
        ),
        "win_brier_tuned_vs_fixed": (
            fold_report["model"]["win_brier"]
            - fold_report["model_fixed_weights"]["win_brier"]
        ),
        "total_mae_vs_train_mean": fold_report["model"]["total_mae"]
        - fold_report["baselines"]["total_mae_train_mean"],
    }
    return fold_report


def _run_holdout_on_matrix(
    df: pd.DataFrame,
    seasons: list[int],
    *,
    feature_cols: list[str],
    fast_train: bool,
    tune_weights: bool,
    min_train_rows: int,
    min_test_rows: int,
    cal_val_fraction: float,
    min_cal_rows: int,
    calibration_method: str,
    cal_train_modes: list[str],
    train_game_models,
    ensemble_predict_proba_batch,
    ensemble_predict_value_batch,
    ensemble_with_weights,
    FEATURE_COLS,
) -> list[dict]:
    sorted_seasons = sorted(set(seasons))
    modes = cal_train_modes or [CAL_TRAIN_SPLIT]
    folds = []
    for test_year in sorted_seasons[1:]:
        train_df = df[df["season_year"] < test_year]
        test_df = df[df["season_year"] == test_year]
        if len(train_df) < min_train_rows or len(test_df) < min_test_rows:
            logger.warning(
                f"Skip holdout {test_year}: train={len(train_df)} test={len(test_df)} "
                f"(need >={min_train_rows} / >={min_test_rows})"
            )
            continue

        for cal_mode in modes:
            fold_report = _evaluate_holdout_fold(
                train_df,
                test_df,
                test_year,
                cal_train_mode=cal_mode,
                fast_train=fast_train,
                tune_weights=tune_weights,
                cal_val_fraction=cal_val_fraction,
                min_cal_rows=min_cal_rows,
                min_train_rows=min_train_rows,
                calibration_method=calibration_method,
                train_game_models=train_game_models,
                ensemble_predict_proba_batch=ensemble_predict_proba_batch,
                ensemble_predict_value_batch=ensemble_predict_value_batch,
                ensemble_with_weights=ensemble_with_weights,
                FEATURE_COLS=FEATURE_COLS,
                feature_cols=feature_cols,
            )
            if fold_report is None:
                logger.warning(
                    f"Skip holdout {test_year} mode={cal_mode}: insufficient rows"
                )
                continue

            logger.info(
                f"Holdout {test_year} [{cal_mode}] ({len(feature_cols)} feats): "
                f'train n={fold_report["n_train"]}, test n={fold_report["n_test"]}'
            )
            folds.append(fold_report)
            cal_method = fold_report["calibrator"]["method"]
            logger.info(
                f"  Win Brier raw={fold_report['model']['win_brier']:.4f} "
                f"ML acc={fold_report['model']['win_ml_accuracy']:.3f} "
                f"calibrated({cal_method})="
                f"{fold_report['model_calibrated']['win_brier']:.4f}"
            )
    return folds


def deferred_retrain_recommended(
    baseline_summary: dict,
    expanded_summary: dict,
    *,
    brier_lift_min: float,
    ml_accuracy_lift_min: float,
) -> dict:
    """Document whether production retrain is warranted from holdout lift."""
    brier_baseline = baseline_summary.get("mean_test_win_brier_model")
    brier_expanded = expanded_summary.get("mean_test_win_brier_model")
    acc_baseline = baseline_summary.get("mean_test_win_ml_accuracy_model")
    acc_expanded = expanded_summary.get("mean_test_win_ml_accuracy_model")
    brier_lift = None
    acc_lift = None
    if brier_baseline is not None and brier_expanded is not None:
        brier_lift = float(brier_baseline - brier_expanded)
    if acc_baseline is not None and acc_expanded is not None:
        acc_lift = float(acc_expanded - acc_baseline)
    meets_brier = brier_lift is not None and brier_lift >= brier_lift_min
    meets_acc = acc_lift is not None and acc_lift >= ml_accuracy_lift_min
    return {
        "brier_lift_vs_baseline": brier_lift,
        "ml_accuracy_lift_vs_baseline": acc_lift,
        "brier_lift_threshold": brier_lift_min,
        "ml_accuracy_lift_threshold": ml_accuracy_lift_min,
        "meets_brier_threshold": meets_brier,
        "meets_ml_accuracy_threshold": meets_acc,
        "retrain_recommended": bool(meets_brier or meets_acc),
        "note": (
            "Retrain + S3 upload only when retrain_recommended is true and full "
            "train can be run locally with data."
        ),
    }


def run_seasonal_holdout(
    seasons: list[int],
    fast_train: bool = True,
    tune_weights: bool = True,
    min_train_rows: int = 400,
    min_test_rows: int = 100,
    cal_val_fraction: float = 0.15,
    min_cal_rows: int = 50,
    calibration_method: str = "auto",
    cal_train_modes: list[str] | None = None,
    feature_cols: list[str] | None = None,
    report_filename_prefix: str = "game_model_eval",
):
    """Season-by-season holdout using the training-feature matrix."""
    from app.services.etl.mlb.game_model import (
        FEATURE_COLS,
        app,
        build_historical_training_data,
        ensemble_predict_proba_batch,
        ensemble_predict_value_batch,
        ensemble_with_weights,
        feature_coverage_report,
        load_park_factors,
        train_game_models,
    )

    cols = feature_cols or list(FEATURE_COLS)

    with app.app_context():
        load_park_factors()
        logger.info(f"Building historical matrix for seasons {seasons} …")
        df = build_historical_training_data(seasons=list(seasons), quick=False)
        if df.empty:
            raise RuntimeError(
                "No training rows produced; check seasons and API access."
            )

        df = df.copy()
        df["season_year"] = pd.to_datetime(df["date"]).dt.year
        df = df.sort_values("date").reset_index(drop=True)

        coverage = feature_coverage_report(df, include_deferred=True)
        logger.info(
            "Feature coverage (pct still at neutral default): "
            + ", ".join(
                f"{r['feature']}={r['pct_at_neutral_default']:.0%}"
                for r in coverage["features"][:8]
                if r["pct_at_neutral_default"] is not None
            )
        )

        sorted_seasons = sorted(set(seasons))
        modes = cal_train_modes or [CAL_TRAIN_SPLIT]
        folds = _run_holdout_on_matrix(
            df,
            seasons,
            feature_cols=cols,
            fast_train=fast_train,
            tune_weights=tune_weights,
            min_train_rows=min_train_rows,
            min_test_rows=min_test_rows,
            cal_val_fraction=cal_val_fraction,
            min_cal_rows=min_cal_rows,
            calibration_method=calibration_method,
            cal_train_modes=modes,
            train_game_models=train_game_models,
            ensemble_predict_proba_batch=ensemble_predict_proba_batch,
            ensemble_predict_value_batch=ensemble_predict_value_batch,
            ensemble_with_weights=ensemble_with_weights,
            FEATURE_COLS=FEATURE_COLS,
        )

        overall = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "seasons_requested": sorted_seasons,
            "n_rows_total": int(len(df)),
            "fast_train": fast_train,
            "tune_weights": tune_weights,
            "calibration": {
                "val_fraction": cal_val_fraction,
                "min_cal_rows": min_cal_rows,
                "method": calibration_method,
                "train_modes": modes,
            },
            "feature_columns": cols,
            "feature_coverage": coverage,
            "folds": folds,
        }

        if folds:
            primary_mode = modes[0]
            primary_folds = [
                f for f in folds if f.get("calibration_train_mode") == primary_mode
            ]
            overall["summary_across_folds"], overall["verdict"] = _summarize_folds(
                primary_folds or folds,
            )
            if len(modes) > 1:
                overall["summary_by_cal_train_mode"] = {}
                overall["verdict_by_cal_train_mode"] = {}
                for mode in modes:
                    mode_folds = [
                        f for f in folds if f.get("calibration_train_mode") == mode
                    ]
                    if mode_folds:
                        s, v = _summarize_folds(mode_folds)
                        overall["summary_by_cal_train_mode"][mode] = s
                        overall["verdict_by_cal_train_mode"][mode] = v

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(OUTPUT_DIR, f"{report_filename_prefix}_{ts}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(overall, fh, indent=2)
        overall["_report_path"] = path
        logger.info(f"Wrote evaluation report: {path}")
        return overall


def run_deferred_feature_comparison(
    seasons: list[int],
    fast_train: bool = True,
    tune_weights: bool = True,
    min_train_rows: int = 400,
    min_test_rows: int = 100,
    cal_val_fraction: float = 0.15,
    min_cal_rows: int = 50,
    calibration_method: str = "auto",
    cal_train_modes: list[str] | None = None,
):
    """Walk-forward eval: baseline FEATURE_COLS vs data-driven promoted deferred cols."""
    from app.services.etl.mlb.game_model import (
        DEFERRED_EVAL_BRIER_LIFT_MIN,
        DEFERRED_EVAL_ML_ACCURACY_LIFT_MIN,
        FEATURE_COLS,
        app,
        build_historical_training_data,
        deferred_feature_coverage_report,
        ensemble_predict_proba_batch,
        ensemble_predict_value_batch,
        ensemble_with_weights,
        feature_coverage_report,
        load_park_factors,
        promote_deferred_features,
        train_game_models,
    )

    with app.app_context():
        load_park_factors()
        logger.info(f"Building historical matrix for seasons {seasons} …")
        df = build_historical_training_data(seasons=list(seasons), quick=False)
        if df.empty:
            raise RuntimeError(
                "No training rows produced; check seasons and API access."
            )

        df = df.copy()
        df["season_year"] = pd.to_datetime(df["date"]).dt.year
        df = df.sort_values("date").reset_index(drop=True)

        promotion = promote_deferred_features(df)
        baseline_cols = list(FEATURE_COLS)
        expanded_cols = promotion["expanded_feature_cols"]
        sorted_seasons = sorted(set(seasons))
        modes = cal_train_modes or [CAL_TRAIN_SPLIT]

        logger.info(
            "Deferred promotion candidates: %s",
            promotion["promoted"] or "(none — expanded == baseline)",
        )

        baseline_folds = _run_holdout_on_matrix(
            df,
            seasons,
            feature_cols=baseline_cols,
            fast_train=fast_train,
            tune_weights=tune_weights,
            min_train_rows=min_train_rows,
            min_test_rows=min_test_rows,
            cal_val_fraction=cal_val_fraction,
            min_cal_rows=min_cal_rows,
            calibration_method=calibration_method,
            cal_train_modes=modes,
            train_game_models=train_game_models,
            ensemble_predict_proba_batch=ensemble_predict_proba_batch,
            ensemble_predict_value_batch=ensemble_predict_value_batch,
            ensemble_with_weights=ensemble_with_weights,
            FEATURE_COLS=FEATURE_COLS,
        )

        expanded_folds = []
        if expanded_cols != baseline_cols:
            expanded_folds = _run_holdout_on_matrix(
                df,
                seasons,
                feature_cols=expanded_cols,
                fast_train=fast_train,
                tune_weights=tune_weights,
                min_train_rows=min_train_rows,
                min_test_rows=min_test_rows,
                cal_val_fraction=cal_val_fraction,
                min_cal_rows=min_cal_rows,
                calibration_method=calibration_method,
                cal_train_modes=modes,
                train_game_models=train_game_models,
                ensemble_predict_proba_batch=ensemble_predict_proba_batch,
                ensemble_predict_value_batch=ensemble_predict_value_batch,
                ensemble_with_weights=ensemble_with_weights,
                FEATURE_COLS=FEATURE_COLS,
            )

        primary_mode = modes[0]
        baseline_primary = [
            f for f in baseline_folds if f.get("calibration_train_mode") == primary_mode
        ]
        expanded_primary = [
            f for f in expanded_folds if f.get("calibration_train_mode") == primary_mode
        ]

        baseline_summary, baseline_verdict = _summarize_folds(
            baseline_primary or baseline_folds,
        )
        expanded_summary = {}
        expanded_verdict = {}
        comparison = {
            "expanded_same_as_baseline": expanded_cols == baseline_cols,
            "promoted_columns": promotion["promoted"],
            "no_lift_reason": None,
        }
        retrain_decision = {
            "retrain_recommended": False,
            "note": "No deferred columns promoted; expanded feature set equals baseline.",
        }

        if expanded_cols != baseline_cols and expanded_primary:
            expanded_summary, expanded_verdict = _summarize_folds(
                expanded_primary or expanded_folds,
            )
            retrain_decision = deferred_retrain_recommended(
                baseline_summary,
                expanded_summary,
                brier_lift_min=DEFERRED_EVAL_BRIER_LIFT_MIN,
                ml_accuracy_lift_min=DEFERRED_EVAL_ML_ACCURACY_LIFT_MIN,
            )
            if baseline_summary and expanded_summary:
                comparison["brier_delta_expanded_minus_baseline"] = (
                    expanded_summary["mean_test_win_brier_model"]
                    - baseline_summary["mean_test_win_brier_model"]
                )
                comparison["ml_accuracy_delta_expanded_minus_baseline"] = (
                    expanded_summary["mean_test_win_ml_accuracy_model"]
                    - baseline_summary["mean_test_win_ml_accuracy_model"]
                )
        elif expanded_cols == baseline_cols:
            comparison["no_lift_reason"] = (
                "No deferred column met promotion threshold on training matrix."
            )

        overall = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "report_type": "deferred_feature_comparison",
            "seasons_requested": sorted_seasons,
            "n_rows_total": int(len(df)),
            "fast_train": fast_train,
            "tune_weights": tune_weights,
            "calibration": {
                "val_fraction": cal_val_fraction,
                "min_cal_rows": min_cal_rows,
                "method": calibration_method,
                "train_modes": modes,
            },
            "deferred_feature_coverage": deferred_feature_coverage_report(df),
            "feature_coverage_all": feature_coverage_report(df, include_deferred=True),
            "promotion": promotion,
            "baseline": {
                "feature_columns": baseline_cols,
                "folds": baseline_folds,
                "summary_across_folds": baseline_summary,
                "verdict": baseline_verdict,
            },
            "expanded": {
                "feature_columns": expanded_cols,
                "folds": expanded_folds,
                "summary_across_folds": expanded_summary,
                "verdict": expanded_verdict,
            },
            "comparison": comparison,
            "retrain_decision": retrain_decision,
        }

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(OUTPUT_DIR, f"game_model_deferred_eval_{ts}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(overall, fh, indent=2)
        overall["_report_path"] = path
        logger.info(f"Wrote deferred comparison report: {path}")
        logger.info(
            "Retrain recommended: %s", retrain_decision.get("retrain_recommended")
        )
        return overall


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="MLB game model walk-forward evaluation + JSON model card",
    )
    p.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        required=True,
        help="Season years to include (e.g. 2023 2024 2025). Need at least two years.",
    )
    p.add_argument(
        "--full-train",
        action="store_true",
        help="Use full RandomizedSearchCV per fold (very slow). Default is fast training.",
    )
    p.add_argument(
        "--no-tune-weights",
        action="store_true",
        help="Keep fixed ensemble weights (0.40/0.25/…) instead of validation tuning.",
    )
    p.add_argument(
        "--min-train",
        type=int,
        default=400,
        help="Minimum training rows required per fold (default 400)",
    )
    p.add_argument(
        "--min-test",
        type=int,
        default=100,
        help="Minimum test rows required per fold (default 100)",
    )
    p.add_argument(
        "--cal-val-fraction",
        type=float,
        default=0.15,
        help="Trailing fraction of train season used to fit probability calibrator (default 0.15)",
    )
    p.add_argument(
        "--min-cal-rows",
        type=int,
        default=50,
        help="Minimum rows in calibration fit slice (default 50)",
    )
    p.add_argument(
        "--calibration-method",
        choices=("auto", "isotonic", "platt"),
        default="auto",
        help="Probability calibrator: auto picks lower Brier on cal slice (default auto)",
    )
    p.add_argument(
        "--cal-train-full",
        action="store_true",
        help="Train ensemble on full train season; fit calibrator on tail only",
    )
    p.add_argument(
        "--compare-cal-train-modes",
        action="store_true",
        help="Run split_train and full_train_tail_cal in one report for comparison",
    )
    p.add_argument(
        "--compare-deferred-features",
        action="store_true",
        help="Walk-forward baseline FEATURE_COLS vs promoted deferred columns",
    )
    p.add_argument(
        "--report-deferred-coverage",
        action="store_true",
        help="Build training matrix and log deferred backfill coverage only",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    seasons = sorted(set(args.seasons))
    if len(seasons) < 2:
        logger.error("Need at least two distinct season years for holdout evaluation.")
        sys.exit(1)

    if args.compare_cal_train_modes:
        cal_modes = [CAL_TRAIN_SPLIT, CAL_TRAIN_FULL]
    elif args.cal_train_full:
        cal_modes = [CAL_TRAIN_FULL]
    else:
        cal_modes = [CAL_TRAIN_SPLIT]

    if args.report_deferred_coverage:
        from app.services.etl.mlb.game_model import (
            app,
            build_historical_training_data,
            load_park_factors,
            promote_deferred_features,
        )

        with app.app_context():
            load_park_factors()
            df = build_historical_training_data(seasons=seasons, quick=False)
            promo = promote_deferred_features(df)
            print(json.dumps(promo["coverage"], indent=2))
            print("\nPromoted:", promo["promoted"] or "(none)")
        return

    if args.compare_deferred_features:
        report = run_deferred_feature_comparison(
            seasons,
            fast_train=not args.full_train,
            tune_weights=not args.no_tune_weights,
            min_train_rows=args.min_train,
            min_test_rows=args.min_test,
            cal_val_fraction=args.cal_val_fraction,
            min_cal_rows=args.min_cal_rows,
            calibration_method=args.calibration_method,
            cal_train_modes=cal_modes,
        )
    else:
        report = run_seasonal_holdout(
            seasons,
            fast_train=not args.full_train,
            tune_weights=not args.no_tune_weights,
            min_train_rows=args.min_train,
            min_test_rows=args.min_test,
            cal_val_fraction=args.cal_val_fraction,
            min_cal_rows=args.min_cal_rows,
            calibration_method=args.calibration_method,
            cal_train_modes=cal_modes,
        )

    def _print_summary(label: str, summ: dict, verdict: dict) -> None:
        if not summ:
            return
        print(f"\n=== Summary ({label}) ===")
        print(
            f"  Model win Brier (raw):            {summ['mean_test_win_brier_model']:.4f}"
        )
        print(
            f"  Model win Brier (calibrated):     {summ['mean_test_win_brier_calibrated']:.4f}"
        )
        print(
            f"  Baseline win Brier (0.5):         {summ['mean_test_win_brier_baseline_0.5']:.4f}"
        )
        if verdict:
            print(
                f"  calibration_improves_brier:       {'yes' if verdict.get('calibration_improves_brier') else 'no'}"
            )

    _print_summary(
        cal_modes[0],
        report.get("summary_across_folds", {}),
        report.get("verdict", {}),
    )
    for mode, summ in report.get("summary_by_cal_train_mode", {}).items():
        if mode == cal_modes[0]:
            continue
        _print_summary(
            mode,
            summ,
            report.get("verdict_by_cal_train_mode", {}).get(mode, {}),
        )
    path = report.get("_report_path")
    if path:
        print(f"\nFull JSON: {path}")


if __name__ == "__main__":
    main()
