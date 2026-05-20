# Deferred parity — implemented (2026-05-20)

Items previously listed as "not ported" that are now wired into YetAI Celery pipelines.

## MLB value bets (`mlb_ev`)

| Item | Detail |
|------|--------|
| Module | `app/services/etl/mlb/mlb_ev.py` → `pred_value_bets` |
| Celery | `app.tasks.etl_pipeline.mlb.ev` |
| Admin | `POST /api/admin/celery/run-task?task_name=app.tasks.etl_pipeline.mlb.ev` (fireable catalog) |
| Pipeline | `run_mlb_update_pipeline` enrichment phase (after weather + blowouts) |
| Env | `ODDS_API_KEY`, optional `EV_HOME_FIELD_EDGE`, `EV_K`, S3 park factors CSV |

## MLB HR ML (`dingerParlay`)

| Item | Detail |
|------|--------|
| Module | `dingerParlay/predict_today.py` → `pred_daily_hr_predictions` |
| Celery | `mlb.hr_predictions` (when env set) |
| Pipeline | `persist` phase if **both** `MLB_DAILY_FEATURES_S3` and `MLB_LINEUP_CSV_S3` are set |
| Env | `MLB_HR_MODEL_S3` (default `s3://yetibets/mlb/hr_model.pkl`) |

## NFL kicker ML ensemble

| Item | Detail |
|------|--------|
| Models | `backend/models/nfl/*.pkl` (copied from YetiBets) |
| Modules | `ml_feature_mapping.py`, `ml_kicker_ensemble.py` |
| Integration | Blends into `kickers.py` after statistical prediction |
| Env | `NFL_MODELS_S3_PREFIX` (e.g. `s3://yetibets/nfl/`), `NFL_KICKER_ML_BLEND_WEIGHT` (default `0.35`) |

QB **passing-yard** ML (`advanced_qb_predictor.py`) remains deferred — current path uses nflverse + Odds API in `qb_dynamic` / `qb_betting`.

## NHL odds edges

| Item | Detail |
|------|--------|
| Module | `nhl/betting_edges.py` |
| Wired in | `daily_predictions.py` for goalie saves, player SOG, team totals |
| Odds API | Reuses `get_player_shots_odds_for_event`, existing goalie/totals helpers |

Thresholds align with YetiBets `generate_daily_predictions.py` (goalie) and tuned SOG/totals bands.

## Still deferred

- MLB `classification_model` retrain CLI, `backtest/` CLIs
- NHL `confirm_starters.py`, live poller, backfill CLIs
- NFL QB warehouse / `advanced_qb_predictor` ensemble for **yards** (not kickers)
- Discord notifications (intentionally removed per YetAI product direction)
