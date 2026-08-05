# MLB Profiles Live Wire-Up — Design

**Status:** Draft for review  
**Date:** 2026-08-05  
**Approach:** Verify-first sequential enable  
**Aligns with:** [MLB_MATCHUP_PROFILES.md](../../../backend/docs/MLB_MATCHUP_PROFILES.md), [ML_PROMOTION.md](../../../backend/docs/ML_PROMOTION.md) § MLB matchup profiles, roadmap Phases 3–5

---

## 1. Problem statement

Matchup profiles (Statcast → ProfileStore → consumers) are implemented through Phase 8, but production consumers are gated by `MLB_PROFILES_ENABLED` (default `0`). Without the flag, strikeouts, hits, and game MC use legacy / non-profile paths, so the accuracy benefit of profile tensors is not live.

**Goal:** Audit production state and wire the existing Phase 3–5 path so profiles are live and correctly connected for:

1. **Strikeouts** — `lineup_matchup_adjusted_strikeouts` / `matchup_k` via ProfileStore  
2. **Hits board** — `matchup_contact_score` / `profile_version` on pred_hitter (and HR daily features merge)  
3. **Game MC** — lineup-weighted lambdas via `profiles/lineup_runs.py`

**Non-goals:**

- Promoting hits shadow ML over heuristic board ranking  
- Meta-learner into game pipeline  
- PA sim pilot into production MC  
- Accuracy backtests / model math changes beyond fixing broken wiring  
- New features or Phase 7+ work

---

## 2. Architecture (unchanged; enable + verify)

```text
Statcast S3 → Beat: statcast_incremental / rebuild_profiles → ProfileStore (Postgres)
                              ↓
                    MLB_PROFILES_ENABLED=1
                              ↓
        ┌─────────────────────┼─────────────────────────┐
        ▼                     ▼                         ▼
  strikeouts.py         hits.py +                 game MC
  (matchup_k)           daily_features            (lineup_runs)
                        (matchup_contact)
```

**Rollback:** Set `MLB_PROFILES_ENABLED=0` on API + celery-worker. Consumers fall back to legacy MLB Stats API / non-profile MC lambdas.

---

## 3. Execution procedure

Stop and fix before advancing to the next step.

### 3.1 Inventory

- Confirm Alembic revisions applied: `20260526_mlb_profiles`, `20260526_hitter_profile_meta`, `20260526_mlb_archetypes` (and any successors).
- Read Railway env: `MLB_PROFILES_ENABLED` on **API** and **celery-worker** (both must match).
- Confirm Beat schedule keys present: `mlb-statcast-incremental`, `mlb-profile-rebuild`, `mlb-projections-daily` (see `celery_app.py`).
- Check strikeout classifier artifact via admin ml-ops status / `prod_mlb_strikeout_counts.py` (S3 head). Missing pickle skips ML O/U blend — restore if absent so K path is fully healthy.

### 3.2 Coverage gate

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_profiles.py --min-batter-coverage 80
```

**Pass criteria:** exit 0; pitcher snapshots exist; sample usage sums ≈ 1.0; `batter_reliability_coverage_pct >= 80`.

**On fail:** Enqueue `app.tasks.etl_pipeline.mlb.statcast_incremental` and/or `mlb.rebuild_profiles` (as-of today). Optionally `mlb_assign_archetypes.py` for cold-start coverage. Re-run verify. **Do not** set the flag until this gate passes.

### 3.3 Code wiring audit (local)

Confirm consumers call ProfileStore when `mlb_profiles_enabled()` is true:

| Surface | Entry points |
|---------|----------------|
| Strikeouts | `lineup_utils.lineup_matchup_adjusted_strikeouts`, `mlb_matchup_analysis`, `profiles/matchup_k.py` |
| Hits / HR features | `hits.py`, `dingerParlay/daily_features.py`, `profiles/matchup_contact.py` |
| Game MC | `profiles/lineup_runs.py` → enrichment before MC apply |

**Allowed fixes:** Broken imports, flag not read on worker path, missing lineup attachment, env not loaded on Celery. **Disallowed:** Changing matchup formulas, promotion of shadow hits ML, wiring PA sim.

### 3.4 Enable

Set `MLB_PROFILES_ENABLED=1` on API + celery-worker; restart/redeploy so workers pick up the env.

### 3.5 Consumer smoke (post-projections)

Trigger or wait for `run_mlb_update_pipeline` / game projections, then verify:

| Surface | Evidence |
|---------|----------|
| Strikeouts | Celery worker logs: `K matchup pitcher=… source=…` with `source` in `{observed, shrunk, archetype, league}` (not `legacy_api`). Smoke: `scripts/smoke_mlb_strikeouts.py`. Note: source is **not** persisted on `pred_strikeout_projections` today — log/smoke evidence is authoritative. |
| Hits | DB columns on pred hitter/homer rows: `profile_version`, `matchup_contact_score` where matchups resolve |
| Game MC | `prod_verify_mlb_monte_carlo.py`: when MC rows exist, `with_lineup_weighted_mc > 0`; no `lineup_weighted_warn` |

### 3.6 Artifact health

If strikeout classifier missing: dry-run then retrain/restore per `MLB_ML_OPS.md` so regression + ML blend both run. Orthogonal to profiles but required for “working together.”

---

## 4. Success criteria

All must be true (with fresh command/output evidence):

1. `MLB_PROFILES_ENABLED=1` on API and celery-worker  
2. `prod_verify_mlb_profiles.py --min-batter-coverage 80` exits 0  
3. Post-pipeline: K worker logs/`smoke_mlb_strikeouts` show non-`legacy_api` matchup sources; hits `profile_version` / contact score populated where expected; MC lineup-weighted when MC present  
4. Beat jobs for Statcast incremental + profile rebuild still scheduled  
5. Strikeout model artifact present (or restored in this engagement)

---

## 5. Failure handling

| Failure | Action |
|---------|--------|
| Coverage &lt; 80% | Rebuild; do not enable flag |
| Migrations missing | Run Database Migrations workflow; stop |
| Flag on but consumers still legacy / `none` | Fix wiring; redeploy; re-smoke |
| MC without `lineup_weighted` | Confirm flag on **worker**; re-run game projections |
| Bad slate after enable | Immediately set `MLB_PROFILES_ENABLED=0` on API + worker |

---

## 6. Authority & constraints

- **Authority:** Flip Railway flags, enqueue Celery rebuilds, restore artifacts after verify gates pass (user-approved).  
- **Evidence before claims:** No completion statements without fresh script/env output in-session.  
- **Scope boundary:** Wire-up only — no accuracy-lift campaigns in this design.

---

## 7. Related docs & scripts

- `backend/docs/MLB_MATCHUP_PROFILES.md`  
- `backend/docs/MLB_ML_OPS.md`  
- `backend/docs/ML_PROMOTION.md` (profile promotion checklist)  
- `scripts/prod_verify_mlb_profiles.py`  
- `scripts/prod_verify_mlb_monte_carlo.py`  
- `scripts/smoke_mlb_strikeouts.py`  
- Celery: `mlb.statcast_incremental`, `mlb.rebuild_profiles`, `run_mlb_update_pipeline`
