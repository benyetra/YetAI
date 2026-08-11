# NFL ML operations

## QB passing yards (Phase 4.3+)

| Mode | Env | Production yards | `model_version` |
|------|-----|------------------|-----------------|
| Tier table (default) | — | Stable tier base (+ injury soft-downgrade) | `tier-v3` |
| ML shadow | — | Tier (unchanged) | `tier-v3`; `feature_importance.ml_shadow_yards` |
| ML promote | `NFL_QB_ML_ENABLED=1` | GBM from S3/local/`models/nfl` | `gbm-qb-yards-YYYYMMDD` |

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

Promotion gate: ML MAE ≥ **10%** better than tier on holdout.

### Latest offline retrain (2026-08-11, nflverse 2023–2025)

| Metric | Value |
|--------|-------|
| Rows | 1140 train+holdout |
| Tier MAE | **61.8** |
| ML MAE | 65.4 |
| Lift | **−5.8%** (worse than tier) |
| Promote? | **No** — keep `NFL_QB_ML_ENABLED` unset/0 |

Artifacts shipped under `backend/models/nfl/` for shadow inference:
`qb_passing_yards.pkl`, `qb_pass_yds_ou.pkl`, `qb_retrain_report.json`.

Re-run:

```bash
cd backend
PYTHONPATH=. python scripts/nfl_retrain_qb_models.py --seasons 2023,2024,2025
# With prod credentials:
PYTHONPATH=. python scripts/nfl_retrain_qb_models.py --seasons 2023,2024,2025 --upload
PYTHONPATH=. python -m app.services.etl.nfl.ml_training.train_qb_model \
  --season-start 2024-09-01 --season-end 2025-02-15 --upload
PYTHONPATH=. python scripts/nfl_backtest.py --quick
```

Local path: `NFL_QB_MODEL_LOCAL` or bundled `backend/models/nfl/`.

## Kicker blend (Phase 4.4+)

| Variable | Purpose |
|----------|---------|
| `NFL_KICKER_ML_BLEND_WEIGHT` | Override default ML blend |
| `NFL_KICKER_BLEND_TUNED_WEIGHT` | Pin walk-forward optimal weight in prod |
| `NFL_MODELS_S3_PREFIX` | Kicker ensemble pickles |

Offline CSV tune (`scripts/nfl_tune_kicker_blend.py --write`) recommended
**0.50** → written to `models/nfl/kicker_blend_tune.json` (auto-loaded when env unset).
Prefer re-tuning from prod `statistical_fgs` / `ml_fgs` / `actual_fg_made` rows.

```bash
# Railway / prod recommendation until prod walk-forward exists:
NFL_KICKER_BLEND_TUNED_WEIGHT=0.5
```

ML FG count uses **attempts × distance-mixture make%** (`kicker_volume.py`).

## Accuracy

`GET` NFL accuracy includes `by_model_version` MAE for QB yards and kicker FG.
