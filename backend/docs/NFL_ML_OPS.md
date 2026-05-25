# NFL ML operations

## QB passing yards (Phase 4.3)

| Mode | Env | Production yards | `model_version` |
|------|-----|------------------|-----------------|
| Tier table (default) | — | `predict_qb_passing_yards` tier + variance | `tier-v1` |
| ML shadow | — | Tier (unchanged) | `tier-v1`; `feature_importance.ml_shadow_yards` |
| ML promote | `NFL_QB_ML_ENABLED=1` | GBM from S3/local | `gbm-qb-yards-YYYYMMDD` |

Promotion gate (backtest on prod DB): ML MAE ≥ **10%** better than tier-only baseline documented in `nfl_backtest_quick_baseline.json`.

## Train + upload

```bash
cd backend
PYTHONPATH=. python -m app.services.etl.nfl.ml_training.train_qb_model \
  --season-start 2024-09-01 --season-end 2025-02-15 --upload
```

Artifacts: `s3://yetibets/nfl/ml_models/qb_passing_yards.pkl` (+ `_metadata.json`).

Local dev: `NFL_QB_MODEL_LOCAL=/path/to/models`

## Backtest

```bash
PYTHONPATH=. python scripts/nfl_backtest.py --quick
```

Offline CI: `tests/test_nfl_backtest_regression.py`, `tests/test_nfl_qb_passing_yards_ml.py`.

## Kicker blend (Phase 4.4)

| Variable | Purpose |
|----------|---------|
| `NFL_KICKER_ML_BLEND_WEIGHT` | Default ML blend (0.35) when no tuned weight |
| `NFL_KICKER_BLEND_TUNED_WEIGHT` | Pin walk-forward optimal weight in prod |
| `NFL_MODELS_S3_PREFIX` | Kicker ensemble pickles |

Kick distance uses `impute_kick_distance()` (kicker avg → `field_goal_data.csv` → league mean), not flat 38.0.

Walk-forward helper: `kicker_blend_tune.walk_forward_blend_weight(records)` with rows
`statistical_fgs`, `ml_fgs`, `actual_fg_made`. Run backtest first, then set tuned weight from CLI output.
