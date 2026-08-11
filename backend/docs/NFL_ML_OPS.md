# NFL ML operations

## QB passing yards (Phase 4.3+)

| Mode | Env | Production yards | `model_version` |
|------|-----|------------------|-----------------|
| Tier table (default) | — | `predict_qb_passing_yards` tier + variance | `tier-v2` |
| ML shadow | — | Tier (unchanged) | `tier-v2`; `feature_importance.ml_shadow_yards` + feature dump |
| ML promote | `NFL_QB_ML_ENABLED=1` | GBM from S3/local | `gbm-qb-yards-YYYYMMDD` |

**Features (v2):** `tier_yards`, `is_backup`, `week`, `confidence`, `season`, plus
`rolling_yards_l3/l5`, `season_avg_yards`, `opp_pass_yds_allowed`, `is_home`,
`rest_days`, `implied_team_total`, `wind_speed`, `temperature`, `dome`.

Form features are leak-safe (prior weeks only). Inference fills them from
nflverse weekly + schedule + `pred_nfl_game_lines` when available.

Promotion gate (backtest on prod DB): ML MAE ≥ **10%** better than tier-only baseline documented in `nfl_backtest_quick_baseline.json`.

Retrain after feature expansion before promoting — older S3 artifacts trained on
the 5-column tier-only matrix are not compatible with the v2 feature order.

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

Offline CI: `tests/test_nfl_backtest_regression.py`, `tests/test_nfl_qb_passing_yards_ml.py`,
`tests/test_nfl_qb_features.py`.

## Kicker blend (Phase 4.4+)

| Variable | Purpose |
|----------|---------|
| `NFL_KICKER_ML_BLEND_WEIGHT` | Default ML blend (0.35) when no tuned weight |
| `NFL_KICKER_BLEND_TUNED_WEIGHT` | Pin walk-forward optimal weight in prod |
| `NFL_MODELS_S3_PREFIX` | Kicker ensemble pickles |

Kick distance uses `impute_kick_distance()` (kicker avg → `field_goal_data.csv` → league mean), not flat 38.0.

ML FG count uses **attempts × make probability** (`estimate_ml_field_goal_volume`),
not the legacy `1.2 + p×2.3` linear map. Attempts come from
`StatisticalKickerPredictor.estimate_field_goal_attempts` (or an explicit
`predicted_attempts` in game context).

Walk-forward helper: `kicker_blend_tune.walk_forward_blend_weight(records)` with rows
`statistical_fgs`, `ml_fgs`, `actual_fg_made`. Run backtest first, then set tuned weight from CLI output.
