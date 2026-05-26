# MLB Matchup Profiles — Phase 5 Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` per task with spec review then code quality review.

**Goal:** Game Monte Carlo uses profile-based lineup-weighted run rates in production, persists `sim_distribution.matchup_meta`, and is verifiable via logs and `prod_verify`.

**Spec:** `docs/superpowers/specs/2026-05-25-mlb-matchup-profiles-roadmap.md` § Phase 5

**Prerequisite:** Phases 0–3 shipped; `MLB_PROFILES_ENABLED=1`; snapshots populated.

**Already on `main`:** `profiles/lineup_runs.py`, `apply_monte_carlo_to_prediction` hook, `tests/test_mlb_lineup_runs.py`.

**Gap:** Daily `get_todays_games()` / MC enrichment do not set `home_lineup` / `away_lineup`, so production MC skips profile adjustment.

---

## Task 1: Attach lineup IDs for MC enrichment

**Files:**
- Modify: `backend/app/services/etl/mlb/monte_carlo.py`
- Modify: `backend/app/services/etl/mlb/profiles/lineup_runs.py` (helper)
- Test: `backend/tests/test_mlb_lineup_runs.py`

**Requirements:**
- Add `attach_lineup_features_for_mc(game: dict, features: dict) -> None` that, when `mlb_profiles_enabled()`:
  - Sets `home_lineup` / `away_lineup` via existing `projected_lineup(home_id)` / `projected_lineup(away_id)` from `lineup_utils` (same fallback as strikeouts).
  - Ensures `home_pitcher_id`, `away_pitcher_id` on features from game if missing.
  - Optionally set `home_pitcher_hand` / `away_pitcher_hand` from `ProfileStore` or statsapi when cheap; default `R` is acceptable if lookup is heavy.
- Call helper from `enrich_predictions_with_monte_carlo` after `build_features(game)` and before `apply_monte_carlo_to_prediction`.
- Do not fetch lineups when profiles disabled.

**Tests:**
- With `MLB_PROFILES_ENABLED=1` and mocked `projected_lineup`, `attach_lineup_features_for_mc` populates lineups.
- `maybe_adjust_rates_from_lineups` returns non-None meta when lineups + pitcher ids present (extend existing test file).

**Verify:**
```bash
cd backend && PYTHONPATH=. .venv/bin/pytest tests/test_mlb_lineup_runs.py -v
```

---

## Task 2: Production logging

**Files:**
- Modify: `backend/app/services/etl/mlb/profiles/lineup_runs.py`

**Requirements:**
- When lineup adjustment applies, log at INFO:
  `MC lineup_weighted game_id=%s home_adj=%s away_adj=%s sources=%s`
- Pass `game_id` through `maybe_adjust_rates_from_lineups` via optional `features.get("game_id")`.

**Verify:** grep-friendly log line; no log when skipped.

---

## Task 3: prod_verify Monte Carlo matchup_meta

**Files:**
- Modify: `backend/scripts/prod_verify_mlb_monte_carlo.py`

**Requirements:**
- In DB check for today's rows: count where `sim_distribution->'matchup_meta'->>'lineup_weighted' = 'true'`.
- WARN (not fail) if MC rows exist but zero lineup_weighted when `MLB_PROFILES_ENABLED` expected.
- Document in `backend/docs/MLB_MATCHUP_PROFILES.md` § Phase 5 verify.

---

## Task 4: Game backtest hook (exit criteria stub)

**Files:**
- Modify: `backend/app/services/etl/mlb/backtest/cli.py` (or document existing path)
- Test: `backend/tests/test_mlb_backtest_cli.py` (if exists) or minimal new test

**Requirements:**
- CLI flag `--mc-lineup-profiles` (or document that `--use-profiles` + lineup fields in data_builder enables Phase 5 path).
- Log summary: % games with `lineup_weighted` meta when MC runs in backtest.

**Exit criteria (manual):** Compare total MAE with/without flag on 2024 holdout — not automated in this task.

---

## Phase 5 exit checklist

- [ ] Daily game pipeline logs `MC lineup_weighted` for most slates
- [ ] `pred_game_projections.sim_distribution.matchup_meta.lineup_weighted` true for today's games
- [ ] `prod_verify_mlb_monte_carlo.py` reports lineup_weighted count
- [ ] Black on touched Python files
