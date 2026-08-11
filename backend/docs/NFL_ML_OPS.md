# NFL ML operations

## QB passing yards (Phase 4.3+)

| Mode | Env | Production yards | `model_version` |
|------|-----|------------------|-----------------|
| Tier table (default) | — | Stable tier base (+ injury soft-downgrade) | `tier-v3` |
| ML shadow | — | Tier (unchanged) | `tier-v3`; `feature_importance.ml_shadow_yards` |
| ML promote | `NFL_QB_ML_ENABLED=1` | Residual GBM (`tier + residual`) | `gbm-qb-residual-YYYYMMDD` |

**Tier v3:** No hash-based week noise. Uncertainty is
`prediction_interval_lower/upper` + confidence. Opt-in legacy noise with
`NFL_QB_TIER_HASH_VARIANCE=1`. Questionable starters: −12 yards + confidence hit
(Out/IR/Doubtful still promote backup).

**Late availability:** Beat jobs
`nfl-gameday-availability-{sun-am,sun-mid,sun-pm,mon}` re-run QB + kickers near
kickoff. Within 3h of KO, Questionable escalates to Out (backup promotion).
Within 12h, Q risk/yard cuts escalate; live backups take an extra −20 yards
(`NFL_QB_LATE_AVAILABILITY=0` to disable).

**Features (v4 residual):** prior form + defense + weather, plus market
(`total_line`, `spread_line`, `pass_yds_line`, `implied_team_total`) and curated
scheme tags (`opp_cover_base`, `opp_man_zone`, `opp_scheme_pressure` from
`defensive_schemes.yaml`).

**O/U classifier:** `qb_ou_classifier` trains `gbm-qb-ou-*` alongside yards GBM.
`qb_betting` blends yards-edge with `P(over)`; disagreement → PASS unless yards
edge is strong (≥10%).

Promotion gate: residual ML MAE ≥ **10%** better than tier on holdout.
**Do not set `NFL_QB_ML_ENABLED=1` unless the gate clears.**

### Latest offline retrain (2026-08-11, residual GBM, nflverse 2023–2025)

| Metric | Value |
|--------|-------|
| Rows | 1140 |
| Holdout | time 20% |
| Tier MAE | **61.8** |
| Residual ML MAE | **61.7** |
| Lift | **+0.2%** (far below 10% gate) |
| Promote? | **No** — keep `NFL_QB_ML_ENABLED` unset/0 |

### Prod DB retrain (2026-08-11, `pred_qb_actuals` 2025 W3–18)

| Metric | Value |
|--------|-------|
| Rows | 360 (train 288 / holdout 72) |
| Holdout | time 20% |
| Tier MAE | **72.8** |
| Residual ML MAE | **69.1** |
| Lift | **+5.1%** (below 10% gate) |
| Promote? | **No** |

### Actuals backfill + multi-season re-eval (2026-08-11)

| Metric | Value |
|--------|-------|
| Rows | **1756** (train 1171 / holdout 585 = season 2025) |
| Real `ou_line` coverage | **386 / 1756 (22%)** — 2025 preds only |
| Tier MAE | **66.7** |
| Residual ML MAE | **64.7** |
| Lift | **+3.0%** (below 10% gate) |
| Promote? | **No** |
| Kicker FG MAE | **0.98** on **479** `pred_kicker_actuals` rows |
| Blend pin | `NFL_KICKER_BLEND_TUNED_WEIGHT=0.5` (CSV walk-forward) |

```bash
export DATABASE_URL=...   # Railway Postgres
cd backend
PYTHONPATH=. python scripts/nfl_backfill_actuals.py --kickers --season 2025
PYTHONPATH=. python scripts/nfl_backfill_actuals.py --qb --seasons 2023,2024,2025
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py
PYTHONPATH=. python scripts/nfl_backtest.py --season 2025 --start-week 1 --end-week 18 --json
PYTHONPATH=. python scripts/nfl_tune_kicker_blend.py --write
```

**Do not enable `NFL_QB_ML_ENABLED=1` unless holdout lift ≥10%.** Real pass-yards
prop lines come from `pred_qb_predictions.ou_line` (2025 coverage only unless
Odds API historical props are backfilled).

Prod replay (`nfl_backtest.py --season 2025`): QB MAE **68.4** (n=407),
kicker MAE **0.98** (n=479), QB O/U hit **46.4%** (n=386).

```bash
export DATABASE_URL=...   # Railway Postgres
cd backend
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py
PYTHONPATH=. python scripts/nfl_backtest.py --season 2025 --start-week 3 --end-week 18 --json
# S3 (needs AWS keys) — only force-upload shadow artifacts; promote still gated:
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py --force-upload --upload-kickers
```

Kicker ensemble lives at `s3://yetibets/nfl/` (`NFL_MODELS_S3_PREFIX=s3://yetibets/nfl/`).
QB yards/O/U artifacts go under `s3://yetibets/nfl/ml_models/`.

**S3 upload (2026-08-11):** refreshed kicker pickles + attempts model pushed to
`s3://yetibets/nfl/`; residual QB + O/U shadow artifacts pushed to
`s3://yetibets/nfl/ml_models/` (promote still **off**).

**Do not enable `NFL_QB_ML_ENABLED=1` until holdout lift ≥10%.**

Artifacts under `backend/models/nfl/` for shadow inference:
`qb_passing_yards.pkl` (residual), `qb_pass_yds_ou.pkl`,
`qb_prod_retrain_report.json`, `qb_prod_backtest_report.json`.
## Kicker blend (Phase 4.4+)

| Variable | Purpose |
|----------|---------|
| `NFL_KICKER_ML_BLEND_WEIGHT` | Override default ML blend |
| `NFL_KICKER_BLEND_TUNED_WEIGHT` | Pin walk-forward optimal weight in prod |
| `NFL_MODELS_S3_PREFIX` | Kicker ensemble pickles |

ML FG count uses **attempts × distance-mixture make%** (`kicker_volume.py`).
Attempts prefer GBM `kicker_attempts.pkl` (from `field_goal_data.csv`), else
heuristic.

Refresh make/miss ensemble + attempts:

```bash
cd backend
PYTHONPATH=. python scripts/nfl_retrain_kicker_models.py
PYTHONPATH=. python scripts/nfl_tune_kicker_blend.py --write
```

```bash
# Railway / prod recommendation until prod walk-forward exists:
NFL_KICKER_BLEND_TUNED_WEIGHT=0.5
```

## Accuracy

`GET` NFL accuracy includes `by_model_version` MAE for QB yards and kicker FG.
