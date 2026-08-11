# NFL ML operations

## QB passing yards (Phase 4.3+)

| Mode | Env | Production yards | `model_version` |
|------|-----|------------------|-----------------|
| Dynamic tier (default) | — | Static name table blended with rolling form | `tier-v3` (+ form blend) |
| ML shadow | — | Dynamic tier (unchanged) | `tier-v3`; `feature_importance.ml_shadow_yards` |
| ML promote | `NFL_QB_ML_ENABLED=1` | Residual GBM (`baseline + residual`) | `gbm-qb-residual-YYYYMMDD` |

**Tier v3:** No hash-based week noise. Uncertainty is
`prediction_interval_lower/upper` + confidence. Opt-in legacy noise with
`NFL_QB_TIER_HASH_VARIANCE=1`. Questionable starters: −12 yards + confidence hit
(Out/IR/Doubtful still promote backup).

**Late availability:** Beat jobs
`nfl-gameday-availability-{sun-am,sun-mid,sun-pm,mon}` re-run QB + kickers near
kickoff. Within 3h of KO, Questionable escalates to Out (backup promotion).
Within 12h, Q risk/yard cuts escalate; live backups take an extra −20 yards
(`NFL_QB_LATE_AVAILABILITY=0` to disable).

**Features (v5 lift levers):** prior form + volume (`rolling_attempts_l3`,
`rolling_ypa_l3`, `rolling_comp_pct_l3`) + defense + weather, market
(`total_line`, `spread_line`, `pass_yds_line`, `line_minus_tier`,
`implied_team_total`), and curated scheme tags. **Dynamic tier** blends the
static name table with leak-safe rolling form (`blend_tier_with_form`). Residual
target is vs a **market-aware baseline** (`0.5*(tier+line)` when a real prop
line is present). Training CV is time-ordered (last 20%). Live `qb_betting`
reinjects `pass_yds_line` after odds attach and refreshes `ml_shadow_yards`.

**O/U classifier:** `qb_ou_classifier` trains `gbm-qb-ou-*` alongside yards GBM.
`qb_betting` blends yards-edge with `P(over)`; disagreement → PASS unless yards
edge is strong (≥10%).

Promotion gate: residual ML MAE ≥ **10%** better than **dynamic tier** on
holdout (`nfl_prod_qb_eval.py` also reports lift vs static tier).
**Do not set `NFL_QB_ML_ENABLED=1` unless the gate clears.**

### Latest Railway promote-gate (2026-08-11, v5 lift levers)

| Metric | Value |
|--------|-------|
| Rows | 1756 (2023–2025 actuals) |
| Holdout | season_2025 (585) |
| Real prop-line rate | 82.7% |
| Dynamic-tier MAE | **65.5** |
| Static-tier MAE | 66.7 |
| Residual ML MAE | **65.0** |
| Lift vs dynamic | **+0.9%** (need ≥10%) |
| Lift vs static | +2.7% |
| Promote | **No** — keep ML shadow-only |

### Prior offline retrain (2026-08-11, residual GBM, nflverse 2023–2025)

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
| Real pass-yds lines | **1453 / 1756 (82.7%)** after Odds historical backfill |
| Tier MAE | **66.7** |
| Residual ML MAE | **71.4** |
| Lift | **−7.0%** (ML worse than tier on 2025 holdout) |
| Promote? | **No** |
| Kicker FG MAE | **0.98** on **479** `pred_kicker_actuals` rows |
| Blend pin | `NFL_KICKER_BLEND_TUNED_WEIGHT=0.5` (CSV walk-forward) |

```bash
export DATABASE_URL=...   # Railway Postgres
export ODDS_API_KEY=...   # paid plan
cd backend
PYTHONPATH=. python scripts/nfl_backfill_actuals.py --kickers --season 2025
PYTHONPATH=. python scripts/nfl_backfill_actuals.py --qb --seasons 2023,2024,2025
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --seasons 2023,2024 --max-credits 5600
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --assign-teams --seasons 2023,2024
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py
PYTHONPATH=. python scripts/nfl_backtest.py --season 2025 --start-week 1 --end-week 18 --json
PYTHONPATH=. python scripts/nfl_tune_kicker_blend.py --write
```

**Do not enable `NFL_QB_ML_ENABLED=1` unless holdout lift ≥10%.** Real pass-yards
prop lines come from `pred_qb_predictions.ou_line` and the historical Odds API
index (`models/nfl/pass_yds_lines.json`).

### Historical pass-yards props (Odds API)

Paid plan. Measured costs: **1 credit / gameday** (events slate) +
**10 credits / game** (`player_pass_yds`, `regions=us`). Responses cache in
`scripts/nfl_odds_cache.db` (gitignored `*.db`); derived lines land in
`models/nfl/pass_yds_lines.json`.

2023–24 REG pull (after cache-key fix): **540 games**, **1093** QB lines,
**~5400 credits** for props (events already cached). Coverage on
`pred_qb_actuals` 2023–24: **~91%**. Re-runs that hit SQLite cost **0**.

```bash
export ODDS_API_KEY=...
cd backend
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --seasons 2023,2024 --dry-run
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --seasons 2023,2024 --max-credits 5600
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --rebuild-from-cache --seasons 2023,2024
export DATABASE_URL=...
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --assign-teams --seasons 2023,2024
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py
```

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

**S3 upload (2026-08-11, post-#89):** v5 residual QB + O/U shadow artifacts
force-uploaded to `s3://yetibets/nfl/ml_models/`
(`gbm-qb-residual-20260811`, market-aware baseline, 28 features including
volume + `line_minus_tier`). Promote still **off** — do **not** set
`NFL_QB_ML_ENABLED=1` (holdout lift +0.9% ≪ 10%). Railway Production Deploy
for `#89` ships the same bundled pickles under `backend/models/nfl/`.

**Prior S3 upload (2026-08-11):** refreshed kicker pickles + attempts model
pushed to `s3://yetibets/nfl/`; earlier residual QB + O/U shadows under
`s3://yetibets/nfl/ml_models/`.

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
