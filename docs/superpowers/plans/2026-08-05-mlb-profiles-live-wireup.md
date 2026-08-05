# MLB Profiles Live Wire-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Confirm Phase 3–5 matchup profiles are live and correctly connected for strikeouts, hits, and game MC lineup lambdas; fix any wiring or data gaps so verify scripts pass with evidence.

**Architecture:** Verify-first sequential enable per `docs/superpowers/specs/2026-08-05-mlb-profiles-live-wireup-design.md`. Consumers already gate on `mlb_profiles_enabled()` / `MLB_PROFILES_ENABLED`. Inventory may find the flag already `1` on Railway — still prove coverage + consumer evidence, then fix only what fails.

**Tech Stack:** Railway (YetAI API + celery-worker), Postgres profile snapshots, Celery Beat, existing verify/smoke scripts under `backend/scripts/`, pytest for wiring regressions.

## Global Constraints

- Wire-up only: no hits shadow-ML promotion, no meta-learner, no PA sim pilot into prod MC, no matchup formula changes.
- Do not set `MLB_PROFILES_ENABLED=1` until `prod_verify_mlb_profiles.py --min-batter-coverage 80` exits 0 (if already `1`, leave it on only while coverage stays ≥80; if coverage fails, rebuild first — do not leave consumers on thin data without a rebuild attempt).
- Flag must match on Railway services **YetAI** (API) and **celery-worker**.
- Strikeout `matchup_source` is log/smoke evidence only (not a column on `pred_strikeout_projections`).
- Evidence before claims: fresh command output required; no “should be fine.”
- Rollback: `MLB_PROFILES_ENABLED=0` on YetAI + celery-worker.
- Never print secrets (DATABASE_URL, AWS keys, passwords) in commits, reports, or chat.
- Commits: stage specific paths only; run backend Black + relevant pytest before commit when Python changes.

## File map

| Path | Role |
|------|------|
| `docs/superpowers/specs/2026-08-05-mlb-profiles-live-wireup-design.md` | Approved design (commit if untracked) |
| `docs/superpowers/plans/2026-08-05-mlb-profiles-live-wireup.md` | This plan |
| `backend/docs/MLB_MATCHUP_PROFILES.md` | Ops docs — update default/live status after success |
| `backend/app/services/etl/mlb/profiles/constants.py` | `mlb_profiles_enabled()` |
| `backend/app/services/etl/mlb/lineup_utils.py` | K matchup ProfileStore path |
| `backend/app/services/etl/mlb/hits.py` | Hits contact / `profile_version` |
| `backend/app/services/etl/mlb/profiles/lineup_runs.py` | MC lineup lambdas |
| `backend/scripts/prod_verify_mlb_profiles.py` | Coverage gate |
| `backend/scripts/prod_verify_mlb_monte_carlo.py` | MC + lineup_weighted evidence |
| `backend/scripts/smoke_mlb_strikeouts.py` | K contract (+ optional `--live`) |
| `.superpowers/sdd/inventory-report.md` | Task 1 evidence (gitignored scratch OK) |

---

### Task 1: Inventory evidence pack

**Files:**
- Create: `.superpowers/sdd/inventory-report.md` (local scratch; do not commit secrets)
- Modify (only if design untracked): commit `docs/superpowers/specs/2026-08-05-mlb-profiles-live-wireup-design.md` + this plan in a docs commit at end of task if not already committed
- Test: N/A (ops inventory)

**Interfaces:**
- Consumes: Railway CLI linked to `yetai-backend` / production; `backend/.env.production` or `scripts/resolve_railway_database_url.py` for DB (do not echo URL)
- Produces: Inventory report with flag values, migration presence, Beat keys, strikeout S3 head present/absent, coverage script raw output path

- [ ] **Step 1: Confirm Railway flags (no secrets in output)**

```bash
cd /Users/byetz/Development/YetAI/YetAI
railway variable list --service YetAI --json | python3 -c "import json,sys; d=json.load(sys.stdin); print('YetAI MLB_PROFILES_ENABLED=', d.get('MLB_PROFILES_ENABLED','<unset>'))"
railway variable list --service celery-worker --json | python3 -c "import json,sys; d=json.load(sys.stdin); print('celery-worker MLB_PROFILES_ENABLED=', d.get('MLB_PROFILES_ENABLED','<unset>'))"
```

Expected: both print `1` (or document mismatch for Task 4).

- [ ] **Step 2: Confirm Beat schedule keys in code**

```bash
rg -n "mlb-statcast-incremental|mlb-profile-rebuild|mlb-projections-daily" backend/app/celery_app.py
```

Expected: all three beat entries present.

- [ ] **Step 3: Ensure local Python env can import backend**

If no `.venv`, create and install:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# if MLB extras needed for live smoke later:
# pip install pybaseball scikit-learn  # only if smoke fails on missing deps
```

- [ ] **Step 4: Check profile tables + coverage (min 80)**

```bash
cd backend
export DATABASE_URL="$(python3 scripts/resolve_railway_database_url.py)"
# Do not print DATABASE_URL
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_profiles.py --json --min-batter-coverage 80 | tee ../.superpowers/sdd/profile-coverage.json
echo EXIT:$?
```

Record exit code and key fields (`latest_pitcher_as_of`, `batter_reliability_coverage_pct`) in `inventory-report.md`.

- [ ] **Step 5: Strikeout / HR model S3 heads via admin or local ml_ops**

Prefer admin API if `YETAI_ADMIN_JWT` or admin email/password available:

```bash
# From backend with admin token in env (do not commit token)
curl -s "$YETAI_API/api/admin/celery/ml-ops-status" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" | python3 -c "import json,sys; d=json.load(sys.stdin); print({k:d.get('s3',{}).get(k) for k in ('strikeout_classifier','hr_model')})"
```

Else:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -c "
from app.services.etl.mlb.ml_ops_status import collect_ml_ops_status
s=collect_ml_ops_status()
print('strikeout', bool((s.get('s3') or {}).get('strikeout_classifier')))
print('hr', bool((s.get('s3') or {}).get('hr_model')))
"
```

- [ ] **Step 6: Write inventory-report.md (no secrets)**

Include: flag values, coverage exit + %, model heads present/absent, whether Task 2 rebuild is required.

- [ ] **Step 7: Commit design + plan only (no inventory secrets)**

```bash
git add docs/superpowers/specs/2026-08-05-mlb-profiles-live-wireup-design.md \
        docs/superpowers/plans/2026-08-05-mlb-profiles-live-wireup.md
git commit -m "$(cat <<'EOF'
docs: add MLB profiles live wire-up design and plan

EOF
)"
```

---

### Task 2: Coverage gate — rebuild if needed

**Files:**
- Modify: none expected (ops); if rebuild scripts broken, fix under `backend/app/services/etl/mlb/profiles/` or `statcast_ingest/`
- Test: `scripts/prod_verify_mlb_profiles.py --min-batter-coverage 80` exits 0

**Interfaces:**
- Consumes: Task 1 coverage exit code
- Produces: Fresh snapshots with `batter_reliability_coverage_pct >= 80`

- [ ] **Step 1: Branch on Task 1 result**

If coverage already passed: write “SKIP rebuild — coverage OK” into report and go to Step 5 commit message note (empty commit not allowed — skip commit if no code change).

If failed: continue.

- [ ] **Step 2: Enqueue Statcast incremental**

```bash
# Requires YETAI_ADMIN_JWT
API="${YETAI_API:-https://api.yetai.app}"
curl -s -X POST "$API/api/admin/celery/enqueue-task" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"task_name":"app.tasks.etl_pipeline.mlb.statcast_incremental"}'
```

Expected: JSON with task id / accepted.

- [ ] **Step 3: Enqueue profile rebuild**

```bash
curl -s -X POST "$API/api/admin/celery/enqueue-task" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"task_name":"app.tasks.etl_pipeline.mlb.rebuild_profiles"}'
```

Wait until worker finishes (rebuild can take 1–3h). Poll Celery admin or re-run coverage periodically.

Alternative local (same DB):

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_rebuild_profiles.py --as-of "$(date +%F)"
```

- [ ] **Step 4: Re-verify coverage**

```bash
cd backend
export DATABASE_URL="$(python3 scripts/resolve_railway_database_url.py)"
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_profiles.py --min-batter-coverage 80
```

Expected: exit 0 and `OK`.

- [ ] **Step 5: Optional archetypes if cold-start still thin**

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_assign_archetypes.py --season 2026
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_profiles.py --min-batter-coverage 80
```

- [ ] **Step 6: Commit only if code fixes were required**

If no code changes: no commit. If fixes: Black + targeted pytest + commit with message describing the fix.

---

### Task 3: Consumer wiring regression tests

**Files:**
- Modify only if tests reveal broken wiring: `lineup_utils.py`, `hits.py`, `lineup_runs.py`, `mlb_matchup_analysis.py`
- Test: `backend/tests/test_mlb_matchup_k.py`, `backend/tests/test_mlb_matchup_contact.py`, `backend/tests/test_mlb_lineup_runs.py`, `backend/tests/test_mlb_profile_constants.py`

**Interfaces:**
- Consumes: `mlb_profiles_enabled()` → ProfileStore consumers
- Produces: Green pytest for profile consumer modules; any wiring fixes merged

- [ ] **Step 1: Run existing consumer tests**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_mlb_profile_constants.py \
  tests/test_mlb_matchup_k.py \
  tests/test_mlb_matchup_contact.py \
  tests/test_mlb_lineup_runs.py
```

Expected: all pass.

- [ ] **Step 2: Static audit — flag gates present**

```bash
rg -n "mlb_profiles_enabled|MLB_PROFILES_ENABLED" \
  backend/app/services/etl/mlb/lineup_utils.py \
  backend/app/services/etl/mlb/hits.py \
  backend/app/services/etl/mlb/profiles/lineup_runs.py \
  backend/app/services/etl/mlb/dingerParlay/daily_features.py \
  backend/app/services/etl/mlb/mlb_matchup_analysis.py
```

Expected: each consumer file references the gate / ProfileStore path.

- [ ] **Step 3: If a test fails or gate missing — fix minimally**

Example invariant already covered by tests: when `MLB_PROFILES_ENABLED=1`, `lineup_runs` / matchup helpers use ProfileStore. Do not change scoring formulas.

- [ ] **Step 4: Re-run the same pytest command**

Expected: PASS.

- [ ] **Step 5: Commit if code changed**

```bash
cd backend && python3 -m black <changed files>
git add <changed paths> <tests if any>
git commit -m "$(cat <<'EOF'
fix(mlb): repair profile consumer wiring for live flag

EOF
)"
```

If no code changes: no commit; note “wiring OK” in report.

---

### Task 4: Align Railway enablement

**Files:** none (ops)

**Interfaces:**
- Consumes: Task 1 flag values + Task 2 coverage pass
- Produces: Both services `MLB_PROFILES_ENABLED=1` after coverage OK

- [ ] **Step 1: If both already `1` and coverage OK — document SKIP**

Write to report: “Flags already enabled; no Railway change.”

- [ ] **Step 2: If mismatch or off and coverage OK — set both to 1**

```bash
railway variable set MLB_PROFILES_ENABLED=1 --service YetAI
railway variable set MLB_PROFILES_ENABLED=1 --service celery-worker
```

Confirm redeploy/restart picks up env (Railway usually redeploys on variable change).

- [ ] **Step 3: Re-read both services**

Same commands as Task 1 Step 1. Expected: both `1`.

- [ ] **Step 4: No code commit unless a helper script was added (YAGNI — prefer none)**

---

### Task 5: Post-enable consumer smoke

**Files:**
- Modify: none expected
- Test: verify scripts + optional live strikeouts

**Interfaces:**
- Consumes: Flag on + coverage OK
- Produces: Evidence for K logs/smoke, hits DB columns, MC `with_lineup_weighted_mc`

- [ ] **Step 1: Enqueue MLB update pipeline (or game projections)**

```bash
API="${YETAI_API:-https://api.yetai.app}"
curl -s -X POST "$API/api/admin/celery/enqueue-task" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"task_name":"app.tasks.etl_pipeline.run_mlb_update_pipeline"}'
```

Wait for completion (or use today’s already-built slate if fresh).

- [ ] **Step 2: Hits + profile columns on today’s slate**

```bash
cd backend
export DATABASE_URL="$(python3 scripts/resolve_railway_database_url.py)"
PYTHONPATH=. .venv/bin/python <<'PY'
from datetime import date
from sqlalchemy import text
from app.services.etl.mlb._db import init_session, close_session, db_session
init_session()
try:
    d = date.today()
    row = db_session.execute(text("""
      SELECT COUNT(*) AS n,
             COUNT(profile_version) AS with_pv,
             COUNT(matchup_contact_score) AS with_contact
      FROM pred_hitter
      WHERE date = :d
    """), {"d": d}).mappings().first()
    print(dict(row))
finally:
    close_session()
PY
```

Expected: `n > 0` and `with_pv > 0` when profiles enabled (contact may be sparse — `with_pv` is the hard signal).

If table/column names differ, inspect models in `backend/app/models/` and adjust query — do not invent columns.

- [ ] **Step 3: Monte Carlo lineup-weighted**

```bash
cd backend
export DATABASE_URL="$(python3 scripts/resolve_railway_database_url.py)"
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_monte_carlo.py --db-only
```

Expected: if `with_mc_tag > 0` then `with_lineup_weighted_mc > 0` and no `lineup_weighted_warn`.

- [ ] **Step 4: Strikeouts smoke**

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_strikeouts.py
# Optional live (needs deps + DB):
# PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_strikeouts.py --live
```

Expected: contract tests PASS. For live: status ok and rows > 0. Check worker logs for `K matchup pitcher=… source=` not stuck on `legacy_api` when flag is on (Railway logs / admin).

- [ ] **Step 5: If MC warn or hits `with_pv==0` — diagnose and fix**

Common causes: flag missing on **worker**, lineup not attached before MC, profile rebuild lag. Fix wiring or re-run rebuild + pipeline. Re-smoke.

- [ ] **Step 6: Commit only if code fixes**

Same Black/pytest/commit discipline as Task 3.

---

### Task 6: Strikeout classifier artifact health

**Files:**
- Ops / optional retrain via existing scripts
- Test: ml-ops status shows strikeout_classifier head

**Interfaces:**
- Consumes: Task 1 S3 head result
- Produces: Classifier present on S3 or documented restore

- [ ] **Step 1: If strikeout_classifier head present — SKIP**

- [ ] **Step 2: If missing — check joined row counts then dry-run retrain**

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/prod_mlb_strikeout_counts.py
PYTHONPATH=. .venv/bin/python scripts/mlb_retrain_strikeouts.py --dry-run
```

If `joined >= 50` (or `MLB_STRIKEOUT_MIN_JOINED_ROWS`):

```bash
# Prefer admin enqueue on prod worker
curl -s -X POST "${YETAI_API:-https://api.yetai.app}/api/admin/celery/ml-ops/retrain-strikeouts" \
  -H "Authorization: Bearer $YETAI_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'
```

- [ ] **Step 3: Re-check S3 head**

Same as Task 1 Step 5. Expected: present.

- [ ] **Step 4: Commit only if training code fixed**

---

### Task 7: Docs sync + success checklist

**Files:**
- Modify: `backend/docs/MLB_MATCHUP_PROFILES.md` (Environment table / Verify section — note production live when evidence passes)
- Modify: optionally one line in `backend/docs/ML_PROMOTION.md` checklist if status outdated

**Interfaces:**
- Consumes: Evidence from Tasks 1–6
- Produces: Docs matching live state; final success checklist in report

- [ ] **Step 1: Update MLB_MATCHUP_PROFILES.md Environment note**

Change the `MLB_PROFILES_ENABLED` row to reflect that production YetAI + celery-worker are set to `1` after this wire-up (keep default-in-code as `0` in `constants.py` — do not flip code default without explicit approval; docs should say “code default 0; prod set to 1”).

Example table cell:

```markdown
| `MLB_PROFILES_ENABLED` | code default `0`; **prod YetAI + celery-worker = `1`** | Enable ProfileStore consumers (Phase 3+) after backfill |
```

- [ ] **Step 2: Append Verify section reminder**

Keep existing verify commands; add one line: “After enablement, confirm hits `profile_version`, MC `with_lineup_weighted_mc`, and K matchup log sources.”

- [ ] **Step 3: Final evidence checklist (all true)**

1. Flags `1` on YetAI + celery-worker  
2. Coverage script exit 0 at min 80  
3. Hits `profile_version` counts > 0 (or documented empty slate reason)  
4. MC lineup-weighted when MC rows exist  
5. Strikeout classifier present (or restored)  
6. Beat keys still in `celery_app.py`

- [ ] **Step 4: Black N/A; commit docs**

```bash
git add backend/docs/MLB_MATCHUP_PROFILES.md
# and ML_PROMOTION.md if touched
git commit -m "$(cat <<'EOF'
docs(mlb): record production matchup profiles as enabled

EOF
)"
```

---

## Spec coverage (self-review)

| Spec section | Task |
|--------------|------|
| Inventory (migrations/flag/Beat/S3) | Task 1 |
| Coverage gate + rebuild | Task 2 |
| Code wiring audit | Task 3 |
| Enable flag | Task 4 |
| Consumer smoke K/hits/MC | Task 5 |
| Strikeout artifact health | Task 6 |
| Success criteria / docs | Task 7 |
| Non-goals (no ML promo / meta / PA sim) | Global Constraints |

## Placeholder scan

No TBD/TODO steps; commands and expected outputs specified.
