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

### CI regression baseline (offline)

Committed fixture: `tests/fixtures/mlb_backtest_quick_baseline.json`. CI runs `tests/test_mlb_backtest_regression.py` only (synthetic metrics; no API calls). See [ML_PROMOTION.md](./ML_PROMOTION.md) § CI baselines.

After an approved model change, refresh the fixture locally:

```bash
cd backend
PYTHONPATH=. python scripts/update_mlb_backtest_baseline.py
pytest tests/test_mlb_backtest_regression.py -q
```

Optional: `--dry-run` prints JSON without writing; `--seed 42` matches default backtest seed.

Import smoke (includes backtest package):

```bash
PYTHONPATH=. python scripts/smoke_import_mlb_etl.py --backtest
```

## Admin API (prod DB — no local DATABASE_URL swap)

```bash
export YETAI_ADMIN_JWT='...'

# Strikeout projections / actuals / joined + model S3 heads + backtest index
curl -s "$API/api/admin/celery/ml-ops-status" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" | jq .

# Same via CLI
PYTHONPATH=. python3 scripts/prod_mlb_strikeout_counts.py

# Enqueue retrain on worker (prod DB)
curl -s -X POST "$API/api/admin/celery/ml-ops/retrain-strikeouts" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}' | jq .

# Enqueue HR rebuild stage
curl -s -X POST "$API/api/admin/celery/ml-ops/hr-rebuild" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"stage":"build-training","season":2024,"use_existing_s3":true}' | jq .

# Quarterly-style backtest (manual — not on Beat by default)
curl -s -X POST "$API/api/admin/celery/enqueue-task" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"task_name":"app.tasks.etl_pipeline.mlb.backtest_quick"}' | jq .
```

Retrain is blocked until `joined >= MLB_STRIKEOUT_MIN_JOINED_ROWS` (default **50**).

### Weekly retrain cadence

1. Check joined row count (admin `ml-ops-status`, `scripts/prod_mlb_strikeout_counts.py`, or `get_strikeout_table_counts()`).
2. When `joined >= MLB_STRIKEOUT_MIN_JOINED_ROWS`, `should_retrain_strikeout_classifier()` returns ready with a reason string — **consider** retrain (not automatic; review recent accuracy first).
3. Dry-run then enqueue or run locally:

```bash
PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py --dry-run
PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py
```

4. After deploy, confirm new `model_version` tags on `pred_strikeout_projections` and segment accuracy via `strikeout_by_model_version` on the MLB accuracy API.

Strikeout ETL **does not** require a loaded classifier: missing pickle logs a warning and skips the ML O/U blend while regression + negbin/line paths still run. Restore the artifact with the retrain commands above.

## Hits board (heuristic + shadow ML)

Production filtering uses `combined_score_heuristic` in `app/services/etl/mlb/hits.py` (`min_combined_score=2` on the daily board).

Backtest (`predict_hits` in `backtest/model_runner.py`) scores two paths:

- **Heuristic** — same weights/gates as production, projected to team hit totals for MAE vs box-score `actual_hits`.
- **Shadow ML** — `app/services/etl/mlb/hits_classifier.py` `predict_p_one_plus_hit()` (logistic-style, no S3). Compared on **1+ hit** board accuracy: pick `ml_prob >= 0.5` vs `actual_hits >= 1` at **team** level.

Hits ML stays **shadow/heuristic-only** in production until backtest `hit_metrics.methods` shows lift over the heuristic MAE / board baseline. Unit tests: `tests/test_mlb_hits_backtest.py`.

## Backtest run index

```bash
PYTHONPATH=. python scripts/mlb_backtest_list_runs.py
PYTHONPATH=. python scripts/mlb_backtest_list_runs.py --compare-prefix d4bc728e
PYTHONPATH=. python scripts/mlb_backtest.py --compare d4bc728e
```

Runs live under `scripts/mlb_backtest_results/runs/` on the machine that executed the backtest (worker disk for Celery `backtest_quick`).

## Strikeout classifier retrain

Module: `app/services/etl/mlb/strikeout_training.py`  
CLI: `scripts/mlb_retrain_strikeouts.py`  
Celery: `app.tasks.etl_pipeline.mlb.retrain_strikeout_classifier`

```bash
PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py --dry-run
PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py
```

Writes `scripts/mlb_strikeout_retrain_metrics.json` on the worker after a successful run. Model: `s3://yetibets/mlb/strikeout_model.pkl`.

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
| `MLB_STRIKEOUT_MIN_JOINED_ROWS` | Minimum joined rows before retrain (default 50) |
| `MLB_STRIKEOUT_MODEL_S3` | Override strikeout model URI for status API |

## Meta-learner (Layer 3)

Module: `app/services/etl/mlb/meta_learner.py` (logistic stacking on `STACK_FEATURES`)  
Evaluation: `app/services/etl/mlb/meta_learner_eval.py`  
Tests: `tests/test_meta_learner_eval.py`

**Default recommendation: SKIP** wiring the meta-learner into `game_projection_pipeline.py` until offline holdout shows **Brier lift ≥ 0.005** (`META_BRIER_LIFT_MIN`) vs the calibrated game ensemble (`xgb_win_prob` / `home_win_prob`). The game model already ships a calibrated ensemble; Layer 3 must prove incremental value or stay off.

| Gate | Threshold |
|------|-----------|
| Brier lift (game − meta) | ≥ `0.005` on temporal holdout |
| `recommend_production_use()` | `True` only when lift meets gate |

### Offline comparison (no DB)

```bash
cd backend
PYTHONPATH=. python -m app.services.etl.mlb.meta_learner --evaluate-offline
PYTHONPATH=. python -m app.services.etl.mlb.meta_learner --evaluate-offline --scenario meta_worse
PYTHONPATH=. python -m app.services.etl.mlb.meta_learner --evaluate-offline --scenario meta_equal
PYTHONPATH=. python -m app.services.etl.mlb.meta_learner --evaluate-offline --scenario meta_better
```

Programmatic (unit tests / notebooks):

```python
from app.services.etl.mlb.meta_learner_eval import (
    compare_meta_learner_vs_game_ensemble,
    evaluate_meta_vs_baseline,
    recommend_production_use,
)

result = compare_meta_learner_vs_game_ensemble(
    {"y_true": y, "p_game": p_game, "p_meta": p_meta}
)
use_meta = recommend_production_use(result)  # False until Brier lift >= 0.005
```

### DB holdout compare (when `DATABASE_URL` is set)

Builds stacking rows from `pred_game_projections` + actuals, trains meta on the early window, scores the last `--holdout-frac` (default 20%) games:

```bash
PYTHONPATH=. python -m app.services.etl.mlb.meta_learner --compare --lookback 60
```

Without `DATABASE_URL`, `--compare` logs a skip and exits 0; use `--evaluate-offline` locally.

Train artifact (optional, not production-gated alone):

```bash
PYTHONPATH=. python -m app.services.etl.mlb.meta_learner --train --lookback 30
```

Writes `app/services/etl/mlb/meta_learner.pkl` (+ S3 when configured). **Do not** call `apply_meta_learner` from the daily game pipeline until `recommend_production_use` is true on a real holdout run.

## Related

- Game model / projections: `game_model.py`, `game_projection_pipeline.py`
- Game holdout eval: `game_model_eval.py`
- Production verify: `scripts/prod_verify_etl.py`
