# MLB ML ops (backtest, retrain, HR rebuild)

Offline tooling ported from YetiBets `scripts/mlb/`. Daily Celery ETL is documented in [MLB_ETL_PARITY.md](./MLB_ETL_PARITY.md).

## Backtest CLI

Package: `app/services/etl/mlb/backtest/`  
Entry: `scripts/mlb_backtest.py`

```bash
cd backend
PYTHONPATH=. python scripts/mlb_backtest.py --quick
PYTHONPATH=. python scripts/mlb_backtest.py --n-games 100 --seed 42
PYTHONPATH=. python scripts/mlb_backtest.py --compare <run_id_prefix>
```

- **Cache:** `backend/scripts/mlb_backtest_cache.db`
- **CSV reports:** `backend/scripts/mlb_backtest_results/`
- **Run JSON (compare):** `backend/scripts/mlb_backtest_results/runs/<uuid>.json`

`--quick` uses 20 games and skips heavy odds/weather fetches. Full runs need network access to MLB/stats APIs and may take several minutes.

Import smoke (includes backtest package):

```bash
PYTHONPATH=. python scripts/smoke_import_mlb_etl.py --backtest
```

## Strikeout classifier retrain

Module: `app/services/etl/mlb/classification_model.py`  
Wrapper: `scripts/mlb_retrain_strikeouts.py`

```bash
PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py
PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py --dry-run
```

Writes `scripts/mlb_strikeout_retrain_metrics.json`. Model: local `strikeout_model.pkl`, S3 `s3://yetibets/mlb/strikeout_model.pkl` (when AWS creds are set).

## dingerParlay HR rebuild

Daily predict path: `hr_ml_build.py` + `dingerParlay/predict_today.py` (see ETL parity doc).

Offline stage orchestrator: `scripts/mlb_hr_rebuild.py`

```bash
PYTHONPATH=. python scripts/mlb_hr_rebuild.py --list-stages
PYTHONPATH=. python scripts/mlb_hr_rebuild.py --stage download-pa --season 2024
PYTHONPATH=. python scripts/mlb_hr_rebuild.py --stage pitcher-stats --season 2024
PYTHONPATH=. python scripts/mlb_hr_rebuild.py --stage park-factors --season 2024
PYTHONPATH=. python scripts/mlb_hr_rebuild.py --stage build-training --season 2024
PYTHONPATH=. python scripts/mlb_hr_rebuild.py --stage train --season 2024 --holdout-date 2024-07-01
```

Defaults use `MLB_HR_S3_PREFIX` (`s3://yetibets/mlb/`). Prior stages must exist on S3 (e.g. `power_scores.csv` from `powerprofile.py`) before `build-training`.

Manifest: `scripts/mlb_hr_rebuild_manifest.json`

**Do not run `--stage train` alone** unless `training_data_<season>.csv` already exists on S3. Production already has `s3://yetibets/mlb/hr_model.pkl`; retrain only when you intentionally rebuild.

Use existing YetiBets artifacts (fast path):

```bash
# Builds training_data_2024.csv from historical_pa.csv + *_all.csv on S3, then trains
python scripts/mlb_hr_rebuild.py --run-through build-training --season 2024 --use-existing-s3
python scripts/mlb_hr_rebuild.py --stage train --season 2024 --holdout-date 2024-07-01
```

`build-training` reads ~5GB `historical_pa.csv` from S3 — allow 30+ minutes.

## Troubleshooting

| Error | Cause | Fix |
|-------|--------|-----|
| `No strikeout training rows` | No joined projection+actual rows in Postgres | Run MLB daily pipeline + `run_mlb_store_actuals` after games |
| `NoSuchKey` on `training_data_2024.csv` | Skipped `build-training` | `--run-through build-training --use-existing-s3` first |
| `command not found: python` | macOS has no `python` shim | `source .venv/bin/activate` or use `.venv/bin/python` |
| `{"detail":"Not Found"}` on Celery curl | Wrong path/body | Use `POST /api/admin/celery/enqueue-task` with `{"task_name":"..."}` |
| Local retrain still 0 after enqueue | `DATABASE_URL` is local DB | Celery writes **prod** Postgres; retrain locally only sees prod if `.env` points there |

## Environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Strikeout retrain + some backtest DB reads |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 model/artifact upload |
| `MLB_HR_S3_PREFIX` | HR artifact prefix |
| `MLB_HR_MODEL_S3` | HR model output path for `train` stage |

## Related

- Game model / projections: `game_model.py`, `game_projection_pipeline.py`
- Production verify: `scripts/prod_verify_etl.py`
