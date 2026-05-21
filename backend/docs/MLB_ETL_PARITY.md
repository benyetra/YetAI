# MLB ETL parity vs YetiBets

Source: `YetiBets/.github/workflows/mlb_daily_projections.yml` and `YetiBets/scripts/mlb/`.

Orchestrator: `app.tasks.etl_pipeline` + Celery Beat:
- **10:00 ET** — `run_mlb_update_pipeline` (projections)
- **04:30 ET** — `run_mlb_store_actuals` (yesterday grading)

## Ported modules (`app/services/etl/mlb/`)

| YetiBets | YetAI | Celery task |
|----------|-------|-------------|
| `strikeouts.py` | `strikeouts.py` | `mlb.strikeouts` |
| `hits.py` | `hits.py` | `mlb.hits` |
| `daily_projection_update.py` (archive K) | `daily_projection_update.py` | `mlb.store_strikeout_projections` |
| `game_projection_pipeline.py` | `game_projection_pipeline.py` | `mlb.game_projections` |
| `daily_batter_projection.py` | `daily_batter_projection.py` | `mlb.batter_projections` |
| `daily_projection_update.py` (K actuals) | same | `mlb.store_strikeout_actuals` |
| `game_projection_pipeline.py` (actuals) | same | `mlb.store_game_actuals` |
| `daily_batter_projection.py` (actuals) | same | `mlb.store_batter_actuals` |
| `weather.py` | `weather.py` | `mlb.weather` |
| `blowouts.py` | `blowouts.py` | `mlb.blowouts` |
| `dingerParlay/predict_today.py` | `dingerParlay/predict_today.py` | optional via env (see below) |

Supporting libs copied: `game_model.py`, `classification_model.py`, `regression_analysis.py`, `bullpen_fatigue.py`, `injury_tracker.py`, `historical_training_backfill.py`, `dingerParlay/*`, etc.

## Execution order (fixed vs legacy GHA)

YetiBets GHA ran `daily_projection_update` **before** `strikeouts`, which archived stale `pred_pitcher` rows. YetAI runs:

1. `strikeouts` → `pred_pitcher`
2. `hits` → `pred_hitter`, `pred_homer`
3. `store_strikeout_projections` → `pred_strikeout_projections`
4. `game_projections` → `pred_game_projections`
5. `batter_projections` → `pred_projected_hits`, `pred_projected_homers`
6. `weather`, `blowouts`

## Environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres |
| `ODDS_API_KEY` | FanDuel lines, game odds |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 models (`s3://yetibets/mlb/`) |
| `MLB_HR_AUTO_BUILD` | `1` → build lineup + daily_features on S3 before predict (after weather) |
| `MLB_HR_S3_PREFIX` | Default `s3://yetibets/mlb/` for generated + static HR artifacts |
| `MLB_DAILY_FEATURES_S3` / `MLB_LINEUP_CSV_S3` | Override paths (defaults under prefix) |
| `MLB_HR_POWER_SCORES_S3`, `MLB_HR_PITCHER_STATS_S3`, etc. | Static training CSVs on S3 |
| `EV_MIN_EDGE` | Min EV % to store value bet (default `0`) |
| `MLB_HR_MODEL_S3` | HR model path (default `s3://yetibets/mlb/hr_model.pkl`) |
| `TOMORROW_IO_API_KEY` or `WEATHER_API_KEY` | `weather.py` |

## Enrichment (daily pipeline)

- `blowouts.py` → `pred_blowout_chances` — `flatten_batters` accepts flat hitter dicts; season year is dynamic (current + prior fallback)
- `mlb_ev.py` → `pred_value_bets` — bulk Odds API h2h, fuzzy team match, `max_ev` / `games_with_odds` in task result
- `hits.py` + `daily_batter_projection.py` — hitter filter min score 2; `pred_projected_hits` scoped to today's `game_time` on boards
- `hr_ml_build.py` + `dingerParlay/predict_today.py` — `mlb.hr_predictions` after weather when `MLB_HR_AUTO_BUILD=1` or CSV env set

## ML ops (offline)

See [MLB_ML_OPS.md](./MLB_ML_OPS.md):

| Tool | Script |
|------|--------|
| Backtest CLI | `scripts/mlb_backtest.py`, `mlb_backtest_list_runs.py` |
| Strikeout retrain | `scripts/mlb_retrain_strikeouts.py`, Celery `mlb.retrain_strikeout_classifier` |
| HR training rebuild | `scripts/mlb_hr_rebuild.py`, `POST /api/admin/celery/ml-ops/hr-rebuild` |
| Prod ML ops status | `GET /api/admin/celery/ml-ops-status`, `scripts/prod_mlb_strikeout_counts.py` |

## Validation

```bash
cd backend && PYTHONPATH=. python scripts/smoke_import_mlb_etl.py
cd backend && PYTHONPATH=. python scripts/smoke_import_mlb_etl.py --backtest
cd backend && PYTHONPATH=. python scripts/validate_mlb_pipeline.py
```

`smoke_import_mlb_etl.py` defaults to pipeline-critical modules (Celery daily path). Use `--all` for the full tree (excludes `backtest.py` / `verify_backtest_prd.py`). Use `--backtest` for the backtest package only.
