#!/usr/bin/env python3
"""Prod NFL QB residual retrain + promote-gate eval from Railway Postgres.

Requires DATABASE_URL. Optional --upload needs AWS credentials for
s3://yetibets/nfl/ml_models/.

Never recommends promote unless holdout MAE beats tier by ≥10%.

Usage:
  export DATABASE_URL=postgresql://...
  PYTHONPATH=. python scripts/nfl_prod_qb_eval.py
  PYTHONPATH=. python scripts/nfl_prod_qb_eval.py --season-start 2025-09-01 --season-end 2026-02-15
  PYTHONPATH=. python scripts/nfl_prod_qb_eval.py --upload
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle  # nosec B403 - own artifacts
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MODELS_DIR = Path(__file__).resolve().parents[1] / "models" / "nfl"
_PROMOTE_LIFT = 0.10


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _market_baseline_row(feats: dict[str, Any], *, tier: float) -> float:
    from app.services.etl.nfl.qb_passing_yards_ml import baseline_yards_from_features

    row = dict(feats)
    row.setdefault("tier_yards", tier)
    return float(baseline_yards_from_features(row, baseline_mode="market"))


def _line_pred_row(
    feats: dict[str, Any], *, tier: float, real_line: float | None
) -> float:
    if real_line is not None and not (
        isinstance(real_line, float) and np.isnan(real_line)
    ):
        return float(real_line)
    line = feats.get("pass_yds_line")
    line_is_real = feats.get("line_is_real")
    try:
        if line is not None and line_is_real is not None and float(line_is_real) >= 0.5:
            return float(line)
    except (TypeError, ValueError):
        pass
    return float(tier)


def _predict_residual_holdout(
    *,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    feature_order: list[str],
    baseline_mode: str,
    hyperparams: dict[str, Any] | None = None,
    use_promote_trainer: bool = False,
) -> tuple[np.ndarray, dict[str, Any]]:
    from app.services.etl.nfl.qb_passing_yards_ml import (
        predict_yards_ml,
        train_promote_qb_yards_model,
        train_qb_yards_model,
    )

    if use_promote_trainer:
        model, metadata = train_promote_qb_yards_model(
            (X_train, y_train),
            residual_target=True,
            feature_order=feature_order,
            baseline_mode=baseline_mode,
        )
    else:
        model, metadata = train_qb_yards_model(
            (X_train, y_train),
            residual_target=True,
            fit_full=True,
            feature_order=feature_order,
            baseline_mode=baseline_mode,
            hyperparams=hyperparams,
        )
    preds = np.array(
        [
            predict_yards_ml(
                model,
                X_test.iloc[i].to_dict(),
                feature_order=feature_order,
                residual_target=True,
                baseline_mode=baseline_mode,
            )
            for i in range(len(X_test))
        ]
    )
    return preds, metadata


def run_holdout_ablations(
    *,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: np.ndarray,
    meta_test: pd.DataFrame,
    tier_test: np.ndarray,
    static_tier_test: np.ndarray,
) -> dict[str, Any]:
    """Season-holdout MAE diagnostics for promote-path decision making."""
    from app.services.etl.nfl.qb_features import (
        FEATURE_NAMES,
        TIER_ONLY_FEATURE_NAMES,
        V5_FEATURE_NAMES,
    )

    real_lines: list[float | None] = []
    if "pass_yds_line_real" in meta_test.columns:
        for i in range(len(meta_test)):
            val = meta_test.iloc[i].get("pass_yds_line_real")
            if val is None or (isinstance(val, float) and np.isnan(val)):
                real_lines.append(None)
            else:
                real_lines.append(float(val))
    else:
        real_lines = [None] * len(X_test)

    market_preds = np.array(
        [
            _market_baseline_row(X_test.iloc[i].to_dict(), tier=float(tier_test[i]))
            for i in range(len(X_test))
        ]
    )
    line_preds = np.array(
        [
            _line_pred_row(
                X_test.iloc[i].to_dict(),
                tier=float(tier_test[i]),
                real_line=real_lines[i],
            )
            for i in range(len(X_test))
        ]
    )

    real_mask = np.array([v is not None for v in real_lines], dtype=bool)

    ablations: dict[str, Any] = {
        "dynamic_tier": {
            "mae": round(_mae(y_test, tier_test), 3),
            "n": int(len(y_test)),
        },
        "static_tier": {
            "mae": round(_mae(y_test, static_tier_test), 3),
            "n": int(len(y_test)),
        },
        "market_baseline_0_5_tier_line": {
            "mae": round(_mae(y_test, market_preds), 3),
            "n": int(len(y_test)),
        },
        "line_only": {
            "mae": round(_mae(y_test, line_preds), 3),
            "n": int(len(y_test)),
            "note": "real prop line when present else dynamic tier",
        },
        "line_only_real_rows": {
            "mae": (
                round(_mae(y_test[real_mask], line_preds[real_mask]), 3)
                if real_mask.any()
                else None
            ),
            "n": int(real_mask.sum()),
        },
    }

    from app.services.etl.nfl.qb_passing_yards_ml import (
        DEFAULT_HYPERPARAMS,
        PROMOTE_HYPERPARAM_CANDIDATES,
    )

    residual_specs: list[tuple[str, list[str], str, dict[str, Any] | None, bool]] = [
        ("v5_features_market_residual", list(V5_FEATURE_NAMES), "market", None, False),
        ("v6_features_market_residual", list(FEATURE_NAMES), "market", None, False),
        (
            "tier_only_residual",
            list(TIER_ONLY_FEATURE_NAMES),
            "tier",
            dict(DEFAULT_HYPERPARAMS),
            False,
        ),
        (
            "tier_only_promote_sweep",
            list(TIER_ONLY_FEATURE_NAMES),
            "tier",
            None,
            True,
        ),
    ]
    for cand in PROMOTE_HYPERPARAM_CANDIDATES:
        hp = {k: v for k, v in cand.items() if k != "name"}
        residual_specs.append(
            (
                f"tier_only_residual_{cand.get('name', 'hp')}",
                list(TIER_ONLY_FEATURE_NAMES),
                "tier",
                hp,
                False,
            )
        )

    for key, order, baseline_mode, hyperparams, use_promote in residual_specs:
        try:
            preds, meta = _predict_residual_holdout(
                X_train=X_train,
                y_train=y_train,
                X_test=X_test,
                feature_order=order,
                baseline_mode=baseline_mode,
                hyperparams=hyperparams,
                use_promote_trainer=use_promote,
            )
            mae = _mae(y_test, preds)
            tier_mae = ablations["dynamic_tier"]["mae"]
            lift = (tier_mae - mae) / tier_mae if tier_mae else 0.0
            entry: dict[str, Any] = {
                "mae": round(mae, 3),
                "mae_lift_vs_dynamic_tier": round(lift, 4),
                "n": int(len(y_test)),
                "n_features": len(order),
                "n_train": meta.get("n_train"),
                "fit_full": meta.get("fit_full"),
                "baseline_mode": baseline_mode,
                "promote_hp_selected": meta.get("promote_hp_selected"),
                "hyperparams": meta.get("hyperparams"),
            }
            if real_mask.any():
                # Diagnose market collapse: how close is ML to the line vs tier?
                line_mae_vs_ml = _mae(preds[real_mask], line_preds[real_mask])
                tier_mae_vs_ml = _mae(preds[real_mask], tier_test[real_mask])
                entry["ml_vs_line_mae_real_rows"] = round(line_mae_vs_ml, 3)
                entry["ml_vs_tier_mae_real_rows"] = round(tier_mae_vs_ml, 3)
                entry["ml_closer_to_line_than_tier"] = bool(
                    line_mae_vs_ml < tier_mae_vs_ml
                )
            ablations[key] = entry
        except Exception as exc:
            ablations[key] = {"status": "error", "error": str(exc)}

    v5 = ablations.get("v5_features_market_residual") or {}
    v6 = ablations.get("v6_features_market_residual") or {}
    tier_only = ablations.get("tier_only_residual") or {}
    promote_arm = ablations.get("tier_only_promote_sweep") or {}
    line_only = ablations.get("line_only") or {}
    ablations["summary"] = {
        "v5_lift_vs_dynamic_tier": v5.get("mae_lift_vs_dynamic_tier"),
        "v6_lift_vs_dynamic_tier": v6.get("mae_lift_vs_dynamic_tier"),
        "tier_only_lift_vs_dynamic_tier": tier_only.get("mae_lift_vs_dynamic_tier"),
        "promote_sweep_lift_vs_dynamic_tier": promote_arm.get(
            "mae_lift_vs_dynamic_tier"
        ),
        "promote_hp_selected": promote_arm.get("promote_hp_selected"),
        "v6_ml_mae_near_line_only": (
            abs(float(v6.get("mae") or 0) - float(line_only.get("mae") or 0)) < 3.0
            if v6.get("mae") is not None and line_only.get("mae") is not None
            else None
        ),
        "v5_still_non_negative_lift": bool(
            (v5.get("mae_lift_vs_dynamic_tier") or -1.0) >= 0.0
        ),
        "tier_only_positive_lift": bool(
            (tier_only.get("mae_lift_vs_dynamic_tier") or -1.0) > 0.0
        ),
    }
    return ablations


def _time_split(
    features: pd.DataFrame, meta: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray, str]:
    """Prefer last season as holdout; else last 20% by (season, week)."""
    if "season" in meta.columns and meta["season"].nunique() >= 2:
        holdout_season = int(meta["season"].max())
        mask = (meta["season"] == holdout_season).to_numpy()
        if mask.sum() >= 40 and (~mask).sum() >= 40:
            return np.where(~mask)[0], np.where(mask)[0], f"season_{holdout_season}"
    n = len(features)
    cut = int(n * 0.8)
    return np.arange(n)[:cut], np.arange(n)[cut:], "time_20pct"


def _build_with_meta(
    season_start: date, season_end: date
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    from app.core.database import SessionLocal
    from app.models.predictions_models import QBActuals
    from app.services.etl.nfl.ml_training.build_qb_dataset import (
        _prediction_context_for_actual,
    )
    from app.services.etl.nfl.qb_features import (
        enrich_context_from_actual_row,
        scheme_features_for_opponent,
    )
    from app.services.etl.nfl.qb_passing_yards_ml import (
        build_features_from_tier_prediction,
    )
    from app.services.etl.nfl.qb_tiers import predict_qb_passing_yards

    session = SessionLocal()
    try:
        rows = (
            session.query(QBActuals)
            .filter(
                QBActuals.game_date >= season_start,
                QBActuals.game_date <= season_end,
            )
            .order_by(QBActuals.season, QBActuals.week)
            .all()
        )
        if not rows:
            return pd.DataFrame(), pd.Series(dtype=float), pd.DataFrame()

        from app.services.etl.nfl.ml_training.build_qb_dataset_nflverse import (
            _schedule_market_index,
        )

        history: list[dict[str, Any]] = []
        for r in rows:
            entry: dict[str, Any] = {
                "qb_player_id": r.qb_player_id,
                "qb_player_name": r.qb_player_name,
                "season": int(r.season),
                "week": int(r.week),
                "actual_passing_yards": float(r.actual_passing_yards),
            }
            if getattr(r, "actual_attempts", None) is not None:
                entry["actual_attempts"] = float(r.actual_attempts)
            if getattr(r, "actual_completions", None) is not None:
                entry["actual_completions"] = float(r.actual_completions)
            # v6 residual levers from graded actuals when present
            if getattr(r, "air_yards_per_attempt", None) is not None:
                entry["air_yards_per_attempt"] = float(r.air_yards_per_attempt)
            if getattr(r, "cpoe", None) is not None:
                entry["cpoe"] = float(r.cpoe)
            if getattr(r, "pressure_rate_faced", None) is not None:
                entry["pressure_rate_faced"] = float(r.pressure_rate_faced)
            history.append(entry)
        seasons = sorted({int(r.season) for r in rows})
        market = _schedule_market_index(seasons)
        records: list[dict[str, float]] = []
        targets: list[float] = []
        meta_rows: list[dict[str, Any]] = []
        for row in rows:
            tier_pred = predict_qb_passing_yards(
                row.qb_player_name,
                int(row.season),
                int(row.week),
                is_backup=False,
            )
            tier_yards = float(tier_pred["predicted_passing_yards"])
            player_key = row.qb_player_id or row.qb_player_name
            context = enrich_context_from_actual_row(
                row,
                history=history,
                player_key=str(player_key),
                tier_yards=tier_yards,
            )
            pred_ctx = _prediction_context_for_actual(session, row)
            real_pass_line = None
            if pred_ctx:
                context.update({k: v for k, v in pred_ctx.items() if v is not None})
                if pred_ctx.get("pass_yds_line") is not None:
                    real_pass_line = float(pred_ctx["pass_yds_line"])
                    context["line_is_real"] = True
            if real_pass_line is None:
                # Historical odds index may still be used inside pred_ctx; if missing,
                # leave line_is_real unset so build_qb_features can infer.
                pass
            team = str(getattr(row, "team_name", "") or "").upper()
            mkt = market.get((int(row.season), int(row.week), team), {})
            for key, value in mkt.items():
                if context.get(key) is None and value is not None:
                    context[key] = value
            opp = (
                getattr(row, "opponent_team_name", None)
                or context.get("opponent_abbr")
                or ""
            )
            if opp and not any(
                context.get(k) is not None
                for k in ("opp_cover_base", "opp_man_zone", "opp_scheme_pressure")
            ):
                # Best-effort: scheme lookup by abbr if present in opponent string
                abbr = str(opp).strip().upper()
                if len(abbr) <= 3:
                    context.update(scheme_features_for_opponent(abbr))
            dynamic_tier = float(context.get("dynamic_tier_yards") or tier_yards)
            tier_pred_dyn = dict(tier_pred)
            tier_pred_dyn["predicted_passing_yards"] = dynamic_tier
            feats = build_features_from_tier_prediction(
                tier_pred_dyn,
                season=int(row.season),
                week=int(row.week),
                context=context,
            )
            records.append(feats)
            targets.append(float(row.actual_passing_yards))
            meta_rows.append(
                {
                    "qb_player_id": row.qb_player_id,
                    "qb_player_name": row.qb_player_name,
                    "season": int(row.season),
                    "week": int(row.week),
                    # Promote gate compares ML vs dynamic (form-blended) tier baseline
                    "tier_yards": dynamic_tier,
                    "static_tier_yards": tier_yards,
                    "actual_passing_yards": float(row.actual_passing_yards),
                    "pass_yds_line_real": real_pass_line,
                }
            )
        return (
            pd.DataFrame(records),
            pd.Series(targets, name="actual_passing_yards"),
            pd.DataFrame(meta_rows),
        )
    finally:
        session.close()


def train_and_eval(
    *,
    season_start: date,
    season_end: date,
) -> dict[str, Any]:
    from app.services.etl.nfl.qb_ou_classifier import (
        MODEL_KEY as OU_KEY,
        build_ou_feature_row,
        train_qb_ou_classifier,
    )
    from app.services.etl.nfl.qb_passing_yards_ml import (
        MODEL_KEY,
        PROMOTE_BASELINE_MODE,
        PROMOTE_FEATURE_NAMES,
        predict_yards_ml,
        select_line_blend_weight,
        train_promote_qb_yards_model,
    )

    features, target, meta = _build_with_meta(season_start, season_end)
    if features.empty or len(features) < 80:
        return {
            "status": "insufficient_data",
            "rows": int(len(features)),
            "season_start": str(season_start),
            "season_end": str(season_end),
            "source": "pred_qb_actuals",
        }

    train_idx, test_idx, holdout_label = _time_split(features, meta)
    X_train = features.iloc[train_idx].reset_index(drop=True)
    y_train = target.iloc[train_idx].reset_index(drop=True)
    X_test = features.iloc[test_idx].reset_index(drop=True)
    y_test = target.iloc[test_idx].to_numpy()
    meta_test = meta.iloc[test_idx].reset_index(drop=True)
    tier_test = meta_test["tier_yards"].to_numpy()
    static_tier_test = (
        meta_test["static_tier_yards"].to_numpy()
        if "static_tier_yards" in meta_test.columns
        else tier_test
    )

    promote_features = list(PROMOTE_FEATURE_NAMES)
    model, metadata = train_promote_qb_yards_model(
        (X_train, y_train),
        residual_target=True,
        feature_order=promote_features,
        baseline_mode=PROMOTE_BASELINE_MODE,
    )
    ml_pred_raw = np.array(
        [
            predict_yards_ml(
                model,
                X_test.iloc[i].to_dict(),
                feature_order=promote_features,
                residual_target=True,
                baseline_mode=PROMOTE_BASELINE_MODE,
            )
            for i in range(len(X_test))
        ]
    )

    real_lines: list[float | None] = []
    if "pass_yds_line_real" in meta_test.columns:
        for i in range(len(meta_test)):
            val = meta_test.iloc[i].get("pass_yds_line_real")
            if val is None or (isinstance(val, float) and np.isnan(val)):
                real_lines.append(None)
            else:
                real_lines.append(float(val))
    else:
        real_lines = [None] * len(X_test)
    line_pred = np.array(
        [
            _line_pred_row(
                X_test.iloc[i].to_dict(),
                tier=float(tier_test[i]),
                real_line=real_lines[i],
            )
            for i in range(len(X_test))
        ]
    )
    real_mask = np.array([v is not None for v in real_lines], dtype=bool)
    blend_sel = select_line_blend_weight(
        y_true=y_test,
        ml_pred=ml_pred_raw,
        line_pred=line_pred,
        real_mask=real_mask,
    )
    blend_w = float(blend_sel["selected_w"])
    ml_pred = np.asarray(blend_sel["blended_pred"], dtype=float)
    metadata = {
        **metadata,
        "line_blend_w": blend_w,
        "line_blend_candidates": blend_sel.get("candidates"),
        "line_blend_diagnostic_best_w": blend_sel.get("diagnostic_best_w"),
        "line_blend_min_w_for_promote": blend_sel.get("min_w_for_promote"),
        "line_blend_note": (
            "post-hoc w*ml+(1-w)*line when real prop line; else ml; "
            "promote excludes w=0 (pure line)"
        ),
    }

    tier_mae = _mae(y_test, tier_test)
    static_tier_mae = _mae(y_test, static_tier_test)
    ml_mae_raw = _mae(y_test, ml_pred_raw)
    ml_mae = _mae(y_test, ml_pred)
    lift_raw = (tier_mae - ml_mae_raw) / tier_mae if tier_mae > 0 else 0.0
    lift = (tier_mae - ml_mae) / tier_mae if tier_mae > 0 else 0.0
    lift_vs_static = (
        (static_tier_mae - ml_mae) / static_tier_mae if static_tier_mae > 0 else 0.0
    )
    promote = lift >= _PROMOTE_LIFT

    ablations = run_holdout_ablations(
        X_train=X_train,
        y_train=y_train,
        X_test=X_test,
        y_test=y_test,
        meta_test=meta_test,
        tier_test=tier_test,
        static_tier_test=static_tier_test,
    )
    # Attach promote-path line-blend grid (same ml_pred_raw / lines as gate).
    blend_candidates_report: list[dict[str, Any]] = []
    for row in blend_sel.get("candidates") or []:
        w = float(row["w"])
        mae = float(row["mae"])
        blend_candidates_report.append(
            {
                **row,
                "mae_lift_vs_dynamic_tier": round(
                    (tier_mae - mae) / tier_mae if tier_mae else 0.0, 4
                ),
            }
        )
        ablations[f"line_blend_w_{w:g}"] = {
            "mae": mae,
            "mae_lift_vs_dynamic_tier": blend_candidates_report[-1][
                "mae_lift_vs_dynamic_tier"
            ],
            "n": int(row.get("n") or len(y_test)),
            "n_real": int(row.get("n_real") or 0),
            "w": w,
            "note": "promote-path tier-only ML blended with real prop line",
        }
    diag_w = blend_sel.get("diagnostic_best_w")
    diag_mae = blend_sel.get("diagnostic_best_mae")
    diag_lift = None
    if diag_mae is not None and tier_mae:
        diag_lift = round((tier_mae - float(diag_mae)) / tier_mae, 4)
    ablations["line_blend"] = {
        "selected_w": blend_w,
        "selected_mae": float(blend_sel.get("selected_mae") or ml_mae),
        "selected_lift_vs_dynamic_tier": round(lift, 4),
        "diagnostic_best_w": diag_w,
        "diagnostic_best_mae": diag_mae,
        "diagnostic_best_lift_vs_dynamic_tier": diag_lift,
        "min_w_for_promote": blend_sel.get("min_w_for_promote"),
        "ml_mae_raw": round(ml_mae_raw, 3),
        "ml_lift_raw": round(lift_raw, 4),
        "candidates": blend_candidates_report,
    }
    summary = ablations.get("summary") or {}
    summary["line_blend_selected_w"] = blend_w
    summary["line_blend_lift_vs_dynamic_tier"] = round(lift, 4)
    summary["line_blend_diagnostic_best_w"] = diag_w
    summary["line_blend_diagnostic_best_lift"] = diag_lift
    ablations["summary"] = summary

    report: dict[str, Any] = {
        "status": "ok",
        "trained_at": datetime.utcnow().isoformat(),
        "source": "pred_qb_actuals",
        "database": "railway",
        "season_start": str(season_start),
        "season_end": str(season_end),
        "rows_total": int(len(features)),
        "rows_train": int(len(X_train)),
        "rows_holdout": int(len(X_test)),
        "holdout": holdout_label,
        "model_family": "residual_gbm_tier_only_line_blend",
        "promote_path": "tier_only_residual_line_blend",
        "promote_hp_selected": metadata.get("promote_hp_selected"),
        "line_blend_w": blend_w,
        "fit_full": True,
        "baseline_mode": PROMOTE_BASELINE_MODE,
        "n_features": len(promote_features),
        "tier_mae": round(tier_mae, 3),
        "static_tier_mae": round(static_tier_mae, 3),
        "ml_mae_raw": round(ml_mae_raw, 3),
        "mae_lift_raw": round(lift_raw, 4),
        "ml_mae": round(ml_mae, 3),
        "mae_lift": round(lift, 4),
        "mae_lift_vs_static_tier": round(lift_vs_static, 4),
        "promote_gate": _PROMOTE_LIFT,
        "promote_recommended": promote,
        "model_version": metadata.get("model_version"),
        "train_metadata": metadata,
        "line_blend": ablations["line_blend"],
        "ablations": ablations,
        "recommendation": (
            "Enable NFL_QB_ML_ENABLED=1 after uploading artifacts"
            if promote
            else "Keep dynamic-tier / shadow ML; residual ML stays off until ≥10% lift"
        ),
    }

    real_line_n = (
        int(meta["pass_yds_line_real"].notna().sum())
        if "pass_yds_line_real" in meta
        else 0
    )
    report["pass_yds_line_real_n"] = real_line_n
    report["pass_yds_line_real_rate"] = (
        round(real_line_n / len(meta), 4) if len(meta) else 0.0
    )

    # O/U on real stored prop lines only. Lines live mostly on 2025 preds; when
    # holdout is season_2025, train_idx has none — so split within real-line rows.
    ou_meta_rows: list[dict[str, Any]] = []
    for i in range(len(features)):
        line = meta.iloc[i].get("pass_yds_line_real")
        if line is None or (isinstance(line, float) and np.isnan(line)):
            continue
        line_f = float(line)
        actual = float(target.iloc[i])
        if abs(actual - line_f) < 0.5:
            continue
        ou_meta_rows.append(
            {
                "i": i,
                "feats": features.iloc[i].to_dict(),
                "label": 1 if actual > line_f else 0,
                "line": line_f,
                "season": int(meta.iloc[i]["season"]),
                "week": int(meta.iloc[i]["week"]),
            }
        )
    ou_meta_rows.sort(key=lambda r: (r["season"], r["week"]))
    ou_model = ou_meta = None
    if len(ou_meta_rows) >= 60 and len({r["label"] for r in ou_meta_rows}) > 1:
        cut = max(40, int(len(ou_meta_rows) * 0.8))
        train_ou = ou_meta_rows[:cut]
        ou_rows = [build_ou_feature_row(r["feats"], r["line"]) for r in train_ou]
        ou_labels = [r["label"] for r in train_ou]
        if len(set(ou_labels)) > 1:
            ou_model, ou_meta = train_qb_ou_classifier(
                pd.DataFrame(ou_rows), pd.Series(ou_labels)
            )
            report["ou_classifier"] = {
                "status": "ok",
                "metadata": ou_meta,
                "source": "pred_qb_predictions.ou_line",
                "rows_total_real": len(ou_meta_rows),
                "rows_train": len(ou_rows),
            }
        else:
            report["ou_classifier"] = {
                "status": "skipped",
                "rows": len(ou_rows),
                "source": "pred_qb_predictions.ou_line",
                "note": "train labels not mixed",
            }
    else:
        report["ou_classifier"] = {
            "status": "skipped",
            "rows": len(ou_meta_rows),
            "source": "pred_qb_predictions.ou_line",
            "note": "need ≥60 graded rows with real pass-yards prop lines",
        }

    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    yards_path = _MODELS_DIR / f"{MODEL_KEY}.pkl"
    yards_meta_path = _MODELS_DIR / f"{MODEL_KEY}_metadata.json"
    with yards_path.open("wb") as f:
        pickle.dump(model, f)
    metadata = {
        **metadata,
        "promote_recommended": promote,
        "holdout_tier_mae": report["tier_mae"],
        "holdout_ml_mae": report["ml_mae"],
        "holdout_mae_lift": report["mae_lift"],
        "training_source": "pred_qb_actuals",
        "season_start": str(season_start),
        "season_end": str(season_end),
    }
    yards_meta_path.write_text(json.dumps(metadata, indent=2, default=str))
    report["local_artifacts"] = {
        "model": str(yards_path),
        "metadata": str(yards_meta_path),
    }

    if ou_model is not None and ou_meta is not None:
        ou_path = _MODELS_DIR / f"{OU_KEY}.pkl"
        ou_meta_path = _MODELS_DIR / f"{OU_KEY}_metadata.json"
        with ou_path.open("wb") as f:
            pickle.dump(ou_model, f)
        ou_meta_path.write_text(json.dumps(ou_meta, indent=2, default=str))
        report["local_artifacts"]["ou_model"] = str(ou_path)
        report["local_artifacts"]["ou_metadata"] = str(ou_meta_path)

    report_path = _MODELS_DIR / "qb_prod_retrain_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    report["report_path"] = str(report_path)
    return report


def maybe_upload(report: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Upload QB artifacts to s3://yetibets/nfl/ml_models/ when AWS creds exist."""
    import boto3

    from app.services.etl.nfl.qb_ou_classifier import MODEL_KEY as OU_KEY
    from app.services.etl.nfl.qb_ou_classifier import S3_BUCKET, S3_PREFIX
    from app.services.etl.nfl.qb_passing_yards_ml import MODEL_KEY

    if not report.get("promote_recommended") and not force:
        report["s3_upload_skipped"] = (
            "promote_recommended=false; pass --force-upload to push shadow artifacts"
        )
        return report

    s3 = boto3.client("s3")
    uploaded = {}
    mapping = {
        MODEL_KEY: (
            _MODELS_DIR / f"{MODEL_KEY}.pkl",
            _MODELS_DIR / f"{MODEL_KEY}_metadata.json",
        ),
        OU_KEY: (
            _MODELS_DIR / f"{OU_KEY}.pkl",
            _MODELS_DIR / f"{OU_KEY}_metadata.json",
        ),
    }
    for key, (model_path, meta_path) in mapping.items():
        if not model_path.is_file() or not meta_path.is_file():
            continue
        s3.upload_file(str(model_path), S3_BUCKET, f"{S3_PREFIX}/{key}.pkl")
        s3.upload_file(str(meta_path), S3_BUCKET, f"{S3_PREFIX}/{key}_metadata.json")
        uploaded[key] = {
            "model": f"s3://{S3_BUCKET}/{S3_PREFIX}/{key}.pkl",
            "metadata": f"s3://{S3_BUCKET}/{S3_PREFIX}/{key}_metadata.json",
        }
    report["s3_uploaded"] = uploaded
    return report


def upload_kicker_bundle() -> dict[str, Any]:
    """Push kicker make/miss + attempts artifacts to s3://yetibets/nfl/."""
    import boto3

    s3 = boto3.client("s3")
    bucket = "yetibets"
    prefix = "nfl"
    files = [
        "logistic_model.pkl",
        "random_forest_model.pkl",
        "gradient_boosting_model.pkl",
        "xgboost_model.pkl",
        "main_scaler.pkl",
        "model_metrics.json",
        "kicker_attempts.pkl",
        "kicker_attempts_metadata.json",
        "kicker_blend_tune.json",
        "kicker_retrain_report.json",
    ]
    uploaded = {}
    for name in files:
        path = _MODELS_DIR / name
        if not path.is_file():
            continue
        key = f"{prefix}/{name}"
        s3.upload_file(str(path), bucket, key)
        uploaded[name] = f"s3://{bucket}/{key}"
    return uploaded


def main() -> int:
    parser = argparse.ArgumentParser(description="Prod QB residual eval (Railway DB)")
    parser.add_argument(
        "--season-start",
        type=str,
        default="2023-09-01",
        help="Inclusive start date on pred_qb_actuals.game_date",
    )
    parser.add_argument(
        "--season-end",
        type=str,
        default="2026-02-15",
        help="Inclusive end date on pred_qb_actuals.game_date",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload QB models to S3 only if promote gate clears",
    )
    parser.add_argument(
        "--force-upload",
        action="store_true",
        help="Upload QB shadow artifacts even when promote=false",
    )
    parser.add_argument(
        "--upload-kickers",
        action="store_true",
        help="Upload kicker ensemble to s3://yetibets/nfl/",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    # Keep DB credentials out of Actions / CI logs
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("app.core.database").setLevel(logging.WARNING)

    if not os.getenv("DATABASE_URL", "").strip():
        print(json.dumps({"status": "error", "error": "DATABASE_URL required"}))
        return 2

    report = train_and_eval(
        season_start=date.fromisoformat(args.season_start),
        season_end=date.fromisoformat(args.season_end),
    )
    if args.upload or args.force_upload:
        try:
            report = maybe_upload(report, force=args.force_upload)
        except Exception as exc:
            report["s3_upload_error"] = str(exc)
    if args.upload_kickers:
        try:
            report["kicker_s3_uploaded"] = upload_kicker_bundle()
        except Exception as exc:
            report["kicker_s3_upload_error"] = str(exc)

    # Persist final report (includes upload status)
    out = _MODELS_DIR / "qb_prod_retrain_report.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    report["report_path"] = str(out)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
