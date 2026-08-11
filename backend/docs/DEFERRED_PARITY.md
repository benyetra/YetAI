# Deferred parity — implemented (2026-05-20)

Items previously listed as "not ported" that are now wired into YetAI Celery pipelines.

## MLB value bets (`mlb_ev`)

| Item | Detail |
|------|--------|
| Module | `app/services/etl/mlb/mlb_ev.py` → `pred_value_bets` |
| Celery | `app.tasks.etl_pipeline.mlb.ev` |
| Admin | Fireable catalog + daily pipeline |
| Env | `ODDS_API_KEY`, optional `EV_HOME_FIELD_EDGE`, `EV_K`, S3 park factors CSV |

## MLB HR ML (`dingerParlay`)

| Item | Detail |
|------|--------|
| Module | `dingerParlay/predict_today.py` → `pred_daily_hr_predictions` |
| Celery | `mlb.hr_predictions` (when env set) |
| Offline rebuild | `mlb.hr_rebuild_stage` + `scripts/mlb_hr_rebuild.py` |
| Env | `MLB_HR_MODEL_S3` (default `s3://yetibets/mlb/hr_model.pkl`) |

## MLB ML ops (offline / admin)

| Item | Detail |
|------|--------|
| Backtest | `app/services/etl/mlb/backtest/` + `scripts/mlb_backtest.py`, `mlb_backtest_list_runs.py` |
| Strikeout retrain | `strikeout_training.py` + `mlb.retrain_strikeout_classifier` |
| Admin status | `GET /api/admin/celery/ml-ops-status` |
| CLI prod counts | `scripts/prod_mlb_strikeout_counts.py` |

## NFL kicker ML ensemble

| Item | Detail |
|------|--------|
| Models | `backend/models/nfl/*.pkl` |
| Integration | Blends into `kickers.py` |
| Env | `NFL_MODELS_S3_PREFIX`, `NFL_KICKER_ML_BLEND_WEIGHT` |

QB **passing-yard** ML (`advanced_qb_predictor.py` as a separate module) remains
deferred as a full port, but the production path now carries v2 matchup/form
features in `qb_features.py` + GBM shadow (`qb_passing_yards_ml.py`). Promote
still requires a retrain that beats the tier baseline by ≥10% MAE.

## NHL odds edges

| Item | Detail |
|------|--------|
| Module | `nhl/betting_edges.py` |
| Wired in | `daily_predictions.py` |

## Still deferred

- NHL `confirm_starters.py`, live poller, backfill CLIs
- NFL QB warehouse / `advanced_qb_predictor` for **yards**
- Discord notifications (intentionally removed)
- Automated Beat schedule for quarterly backtest (admin enqueue only; see `MLB_ML_OPS.md`)
