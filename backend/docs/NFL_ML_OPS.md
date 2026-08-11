# NFL ML operations

## QB passing yards (Phase 4.3+)

| Mode | Env | Production yards | `model_version` |
|------|-----|------------------|-----------------|
| Tier table (default) | — | Stable tier base (+ injury soft-downgrade) | `tier-v3` |
| ML shadow | — | Tier (unchanged) | `tier-v3`; `feature_importance.ml_shadow_yards` |
| ML promote | `NFL_QB_ML_ENABLED=1` | GBM from S3/local | `gbm-qb-yards-YYYYMMDD` |

**Tier v3:** No hash-based week noise. Uncertainty is
`prediction_interval_lower/upper` + confidence. Opt-in legacy noise with
`NFL_QB_TIER_HASH_VARIANCE=1`. Questionable starters: −12 yards + confidence hit
(Out/IR/Doubtful still promote backup).

**Features (v3):** `tier_yards`, `is_backup`, `week`, `confidence`, `season`,
`rolling_yards_l3/l5`, `season_avg_yards`, `opp_pass_yds_allowed`,
`opp_def_epa`, `opp_pressure_rate`, `injury_risk`, `is_home`, `rest_days`,
`implied_team_total`, `wind_speed`, `temperature`, `dome`.

**O/U classifier:** `qb_ou_classifier` trains `gbm-qb-ou-*` alongside yards GBM.
`qb_betting` blends yards-edge with `P(over)`; disagreement → PASS unless yards
edge is strong (≥10%).

Promotion gate (backtest on prod DB): ML MAE ≥ **10%** better than tier-only baseline documented in `nfl_backtest_quick_baseline.json`.

Retrain after feature expansion before promoting — older S3 artifacts trained on
narrower feature matrices are not compatible with the current feature order.

## Train + upload

```bash
cd backend
PYTHONPATH=. python -m app.services.etl.nfl.ml_training.train_qb_model \
  --season-start 2024-09-01 --season-end 2025-02-15 --upload
```

Artifacts:
- `s3://yetibets/nfl/ml_models/qb_passing_yards.pkl` (+ metadata)
- `s3://yetibets/nfl/ml_models/qb_pass_yds_ou.pkl` (+ metadata) when O/U labels exist

Local dev: `NFL_QB_MODEL_LOCAL=/path/to/models`

## Backtest

```bash
PYTHONPATH=. python scripts/nfl_backtest.py --quick
```

Offline CI: `tests/test_nfl_backtest_regression.py`, `tests/test_nfl_qb_*`,
`tests/test_nfl_kicker_blend_tune.py`, `tests/test_nfl_accuracy_model_version.py`.

Accuracy API includes `by_model_version` MAE for QB yards and kicker FG.

## Kicker blend (Phase 4.4+)

| Variable | Purpose |
|----------|---------|
| `NFL_KICKER_ML_BLEND_WEIGHT` | Override default ML blend |
| `NFL_KICKER_BLEND_TUNED_WEIGHT` | Pin walk-forward optimal weight in prod |
| `NFL_MODELS_S3_PREFIX` | Kicker ensemble pickles |

Default blend weight is **0.30** (was 0.35) with the volume model.

Kick distance uses `impute_kick_distance()` (kicker avg → CSV → league mean).

ML FG count uses **attempts × distance-mixture make%** (`kicker_volume.py`),
blending the binary FG classifier with band make rates — not `1.2 + p×2.3`.

Attempts use `estimate_attempts_heuristic` (RZ, 3rd down, pace, script, weather).

Walk-forward helper: `kicker_blend_tune.walk_forward_blend_weight(records)` with rows
`statistical_fgs`, `ml_fgs`, `actual_fg_made`. Run backtest first, then set tuned weight from CLI output.
