# WNBA Totals ML — Under-1 Residual MAE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve WNBA totals residual GBM training/eval so holdout **residual MAE ≤ 1.0** on a time-based split, with upload blocked when the gate fails.

**Architecture:** Fix train/serve skew and leakage first (point-in-time team pace/ORTG/DRTG, time holdout, aligned heuristic replay). Add evaluation + MAE gate mirroring prop models. Extend features (`market_minus_heuristic`) and regularize GBM. Report heuristic vs ML **full-total** MAE separately (full-total MAE < 1 is not a realistic target vs market).

**Tech Stack:** Python, sklearn GradientBoostingRegressor, SQLAlchemy (`WNBARecentGames`, `WNBATotalsActuals`), existing `totals_ml.py` inference path.

**Current baseline (602 rows, random 80/20):** train residual MAE ~7.4, test ~13.2. Production ML disabled (`WNBA_TOTALS_ML_ENABLED` unset).

---

## File map

| File | Responsibility |
|------|----------------|
| `ml_training/team_stats_as_of.py` | Point-in-time team pace/ORTG/DRTG from `WNBARecentGames` |
| `ml_training/totals_training_eval.py` | Time-based split + residual/full-total MAE metrics |
| `ml_training/validate_totals_model.py` | MAE gate check before S3 upload |
| `ml_training/build_totals_dataset.py` | Use as-of stats; return `game_date` index |
| `ml_training/train_totals_model.py` | Time split train; gate on upload |
| `totals_ml.py` | Add `market_minus_heuristic` feature |
| `ml_training/config.py` | `TOTALS_RESIDUAL_MAE_GATE = 1.0` |
| `tests/test_wnba_totals_training_eval.py` | Unit tests for split/metrics/gate |

---

### Task 1: Point-in-time team stats helper

**Files:**
- Create: `backend/app/services/etl/wnba/ml_training/team_stats_as_of.py`
- Test: `backend/tests/test_wnba_team_stats_as_of.py`

- [ ] **Step 1:** Write failing test — team stats use only games with `game_date < as_of`
- [ ] **Step 2:** Implement bulk preload + `pace_and_efficiency_as_of(team_name, as_of) -> dict`
- [ ] **Step 3:** Run pytest on new test file
- [ ] **Step 4:** Commit

---

### Task 2: Training evaluation module (time split + metrics)

**Files:**
- Create: `backend/app/services/etl/wnba/ml_training/totals_training_eval.py`
- Test: `backend/tests/test_wnba_totals_training_eval.py`

- [ ] **Step 1:** Write failing tests for `time_holdout_split(dates, test_fraction=0.2)` (last 20% by date)
- [ ] **Step 2:** Implement `evaluate_holdout(model, X, y, heuristics, actuals)` returning residual + full-total MAE for heuristic baseline and ML
- [ ] **Step 3:** Run pytest
- [ ] **Step 4:** Commit

---

### Task 3: Wire as-of stats + dates into dataset builder

**Files:**
- Modify: `backend/app/services/etl/wnba/ml_training/build_totals_dataset.py`
- Modify: `backend/tests/test_wnba_build_totals_dataset.py`

- [ ] **Step 1:** Update tests — `build()` returns `(X, y, dates)`; replay path uses as-of cache
- [ ] **Step 2:** Replace `_preload_team_stats` season snapshot with `team_stats_as_of.preload(season_start, season_end)`
- [ ] **Step 3:** Pass `actual.game_date` into heuristic replay
- [ ] **Step 4:** Run pytest for build_totals tests
- [ ] **Step 5:** Commit

---

### Task 4: Extended feature + config gate

**Files:**
- Modify: `backend/app/services/etl/wnba/totals_ml.py`
- Modify: `backend/app/services/etl/wnba/ml_training/config.py`
- Create: `backend/app/services/etl/wnba/ml_training/validate_totals_model.py`
- Modify: `backend/tests/test_wnba_totals_ml.py`

- [ ] **Step 1:** Add `market_minus_heuristic` to `_FEATURE_NAMES` and `features_from_projection`
- [ ] **Step 2:** Add `TOTALS_RESIDUAL_MAE_GATE = 1.0` to config
- [ ] **Step 3:** Implement `validate_holdout(metadata) -> {passes_gate, ...}`
- [ ] **Step 4:** Update totals_ml tests
- [ ] **Step 5:** Commit

---

### Task 5: Retrain pipeline — time split, regularization, gated upload

**Files:**
- Modify: `backend/app/services/etl/wnba/ml_training/train_totals_model.py`
- Modify: `.github/workflows/wnba-train-totals-model.yml`
- Modify: `backend/docs/WNBA_ETL_PARITY.md`

- [ ] **Step 1:** Replace `train_test_split` with time holdout via `totals_training_eval`
- [ ] **Step 2:** Tighten hyperparams (`max_depth=3`, `min_samples_leaf=5`, `n_estimators=150`)
- [ ] **Step 3:** On `--upload`, call validate; return `status: gate_failed` if holdout residual MAE > 1.0
- [ ] **Step 4:** Metadata includes `heuristic_holdout_mae`, `ml_holdout_mae`, `full_total_holdout_mae`
- [ ] **Step 5:** Document metrics + gate in parity doc
- [ ] **Step 6:** Run full backend pytest + black
- [ ] **Step 7:** Commit

---

### Task 6: Production verification (manual)

- [ ] Backfill totals actuals from spread if needed
- [ ] Run train without upload; inspect holdout metrics
- [ ] Run train with `--upload` only if gate passes
- [ ] Enable `WNBA_TOTALS_ML_ENABLED=1` only after shadow MAE beats heuristic on recent slate

---

## Success criteria

| Metric | Target |
|--------|--------|
| Holdout **residual** MAE (time split) | ≤ **1.0** |
| Holdout full-total ML MAE | Beat heuristic (report only) |
| Upload without gate pass | Blocked |
| Unit tests | Green |

## Risk note

With ~600 labeled games, **residual MAE < 1** may remain unreachable until more seasons are backfilled (2021–2023) or market-blend serving is adopted. This plan builds the correct measurement and gating infrastructure; data volume is the likely bottleneck if the gate still fails after Tasks 1–5.
