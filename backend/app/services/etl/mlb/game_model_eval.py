"""Walk-forward evaluation and model card for ``scripts/mlb/game_model.py``.

Builds the same historical training matrix used for training, then for each
test season trains only on prior seasons and scores out-of-sample metrics
against simple baselines. Writes a JSON report under ``scripts/mlb/backtest_results/``.

Example::

    cd YetiBets && source .venv/bin/activate
    python scripts/mlb/game_model_eval.py --seasons 2023 2024 2025
    python scripts/mlb/game_model_eval.py --seasons 2024 2025 --no-tune-weights
    # JSON includes calibration_buckets_raw / calibration_buckets_calibrated
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
) -> dict | None:
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
    )

    X_te = test_df[FEATURE_COLS].fillna(0).values
    X_cal = cal_df[FEATURE_COLS].fillna(0).values
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

        coverage = feature_coverage_report(df)
        logger.info(
            "Feature coverage (pct still at neutral default): "
            + ", ".join(
                f"{r['feature']}={r['pct_at_neutral_default']:.0%}"
                for r in coverage["features"][:8]
                if r["pct_at_neutral_default"] is not None
            )
        )

        sorted_seasons = sorted(set(seasons))
        folds = []
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
                "train_modes": cal_train_modes or [CAL_TRAIN_SPLIT],
            },
            "feature_columns": list(FEATURE_COLS),
            "feature_coverage": coverage,
            "folds": folds,
        }

        modes = cal_train_modes or [CAL_TRAIN_SPLIT]

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
                )
                if fold_report is None:
                    logger.warning(
                        f"Skip holdout {test_year} mode={cal_mode}: insufficient rows"
                    )
                    continue

                logger.info(
                    f'Holdout {test_year} [{cal_mode}]: train n={fold_report["n_train"]}, '
                    f'cal fit n={fold_report["n_cal_fit"]}, test n={fold_report["n_test"]}'
                )
                folds.append(fold_report)

                cal_method = fold_report["calibrator"]["method"]
                logger.info(
                    f"  Win Brier raw={fold_report['model']['win_brier']:.4f} "
                    f"calibrated({cal_method})="
                    f"{fold_report['model_calibrated']['win_brier']:.4f} "
                    f"vs 0.5={fold_report['baselines']['win_brier_always_0.5']:.4f}"
                )

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
        path = os.path.join(OUTPUT_DIR, f"game_model_eval_{ts}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(overall, fh, indent=2)
        overall["_report_path"] = path
        logger.info(f"Wrote evaluation report: {path}")
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
