# MLB Matchup Profiles & Historical Backfill — Roadmap

**Status:** Draft for review  
**Date:** 2026-05-25  
**Aligns with:** Golden PRD Modules 2 (features), 3 (Bayesian), 5 (distributions), 6 (MLB PA sim); YetAI `lineup_utils`, `mlb_matchup_analysis`, game-level MC MVP

---

## 1. Problem statement

Strikeout and hit models today mix season aggregates with **live MLB Stats API** pitch splits (`mlb_batter_analysis`, `mlb_pitcher_analysis`). When a batter or pitcher has thin samples—or no prior meeting—matchup logic **silently skips** (`if not bp: continue`), so projections behave like generic season stats.

**Goal:** Build **durable player profiles** (pitch-type × location × handedness) from **years of pitch-level history**, apply **shrinkage toward league/archetype priors**, and wire profiles into **automated daily pipelines** so production never waits months for signal.

**Non-goal (v1):** Full 10k PA-level correlated game sim (PRD Module 6 end-state). v1 delivers profiles + prop adjustments + optional lineup-weighted game lambdas.

---

## 2. Current state (YetAI)

| Asset | Location | Gap |
|-------|----------|-----|
| Pitcher usage + location | `mlb_pitcher_analysis.fetch_pitcher_data` | Live API only; no historical store |
| Batter vs pitch + zones | `mlb_batter_analysis.fetch_batter_performance_vs_pitches` | Same |
| Lineup K adjustment | `lineup_utils.lineup_matchup_adjusted_strikeouts` | Skips missing batters |
| Single batter K factor | `mlb_matchup_analysis.matchup_adjusted_strikeouts` | No shrinkage |
| Statcast proxies | `statcast_features.py` | Season-level, not pitch tensors |
| Historical PA download | `dingerParlay/download_historical_pa.py` (pybaseball) | HR path only; not integrated |
| Game MC | `monte_carlo.py` + pipeline | Team runs; not profile-driven |
| Cron | `run_mlb_update_pipeline` → `mlb.game_projections` | MC on; profiles not |

---

## 3. Target architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│  INGEST (one-time backfill + daily delta)                        │
│  Statcast pitch-level → raw store (S3 parquet + optional PG)     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  AGGREGATE (batch + nightly incremental)                         │
│  Rolling windows: 7d / 30d / season / 3yr decay-weighted         │
│  Dimensions: batter×pitch×zone×vs_hand, pitcher×pitch×zone     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  PROFILE ENGINE (shrinkage + archetypes)                         │
│  Posterior rates, reliability weights, cold-start archetypes     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  MATCHUP SCORER (vector dot-product style)                     │
│  Σ usage_p × (batter_skill_p − league_p) × reliability          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
  strikeouts.py      daily_batter_projection   game_projection_pipeline
  (K, IP)            (hits, HR boards)         (lineup-weighted λ → MC)
```

### 3.1 Profile tensors (canonical)

**Pitcher profile** (per `pitcher_id`, `as_of_date`, window):

- `usage[pitch_type]` → sums to 1
- `location[pitch_type][zone]` → high_inside, low_outside, … (existing buckets)
- `velo`, `spin` optional means per type
- `hand`, `role` (SP/RP)
- `n_pitches` per window

**Batter profile** (per `batter_id`, `as_of_date`, `vs_hand`, window):

- `whiff_rate[pitch_type]`, `xwoba` or `slug` proxy per type
- `cold_zones` / `hot_zones` (zone keys aligned with pitcher buckets)
- `n_pitches`, `n_pa` per type
- Platoon splits always stored separately (LHP/RHP)

**Matchup score** (deterministic, fast):

```text
delta_k = Σ_p usage_pitcher[p] × reliability_b[p] × (whiff_b[p] − league_whiff[p])
         + location_overlap_bonus(p)
```

Optional H2H term when `n_pa_batter_vs_pitcher ≥ 20` (small weight, capped).

### 3.2 Shrinkage (Bayesian-lite, PRD Module 3)

Use **empirical Bayes** (no MCMC in v1):

- Prior: league average for `(pitch_type, vs_hand)` or **archetype** prior (e.g. “power RH bat”, “cutter LHP”).
- Likelihood: batter/pitcher observed rates with binomial or Beta-Binomial for whiff%, Normal for xwOBA.
- Output: `posterior_mean`, `posterior_var`, `reliability ∈ [0,1]` for downstream weighting.

Archetypes (v1.5): cluster on Statcast traits (EV, LA, chase%, pull%) → 8–12 batter types; 6–8 pitcher types. Assign rookies/trades to nearest cluster when `n < threshold`.

---

## 4. Historical data strategy (no “wait from today”)

### 4.1 Source of truth

| Source | Years | Granularity | Use |
|--------|-------|-------------|-----|
| **Statcast** (pybaseball / Baseball Savant) | 2015–present | Pitch-level | Primary for profiles |
| MLB Stats API | Current + prior season | Aggregated splits | Validation + fallback |
| Internal `pred_*` actuals | YetAI history | Game/prop outcomes | Backtest labels |

Reuse existing `dingerParlay/download_historical_pa.py` pattern; generalize into **`mlb_statcast_ingest`**.

### 4.2 Storage layout

**Recommended:** S3 parquet partitioned by `season/month` + Postgres **aggregate tables** for fast API/pipeline reads.

| Store | Contents |
|-------|----------|
| `s3://yetibets/mlb/statcast/pitches/season=YYYY/month=MM/` | Raw pitch rows (select columns only) |
| `mlb_pitcher_profile_snapshots` | One row per pitcher×window×as_of_date |
| `mlb_batter_profile_snapshots` | One row per batter×vs_hand×window×as_of_date |
| `mlb_matchup_features` | Optional precomputed slate rows (game_id, batter_id, pitcher_id, features JSON) |

Raw retention: 2015+ (~10 seasons) ≈ 7–8M rows/season → plan **column pruning** and parquet compression (~2–4 GB/season compressed).

### 4.3 Backfill execution

| Job | Trigger | Duration estimate |
|-----|---------|-------------------|
| `mlb.statcast_backfill_season` | One-time GH Actions / admin enqueue per season | ~2–4 h/season (rate limits) |
| `mlb.statcast_backfill_incremental` | Daily after games | Minutes |
| `mlb.rebuild_profiles` | After backfill chunk or nightly | 10–30 min full league |
| `mlb.rebuild_profiles_point_in_time` | Backtest only | Per backtest date |

**Point-in-time rule:** For backtests, profiles must use only pitches with `game_date < projection_date` (no leakage).

### 4.4 Automation hooks

Add to Celery catalog (`celery_tasks.py`):

- `app.tasks.etl_pipeline.mlb.statcast_incremental`
- `app.tasks.etl_pipeline.mlb.rebuild_profiles`
- `app.tasks.etl_pipeline.mlb.statcast_backfill` (admin-only, season param)

Schedule:

- **Incremental Statcast:** 05:30 ET (after West Coast games)
- **Profile rebuild:** 06:00 ET (before 10:00 ET MLB projections)
- **Existing** `run_mlb_update_pipeline` unchanged order; strikeouts/hits read DB profiles instead of live fetch

---

## 5. Phased roadmap

### Phase 0 — Spec & schema (1 week)

**Deliverables**

- Alembic: `mlb_batter_profile_snapshots`, `mlb_pitcher_profile_snapshots`, indexes on `(player_id, as_of_date, window)`.
- JSON schema for profile blobs (versioned `profile_version`).
- Feature flag: `MLB_PROFILES_ENABLED=0|1`.

**Exit criteria**

- Migrations on staging; empty tables + ORM models.

---

### Phase 1 — Historical Statcast ingest (2–3 weeks)

**Deliverables**

- `app/services/etl/mlb/statcast_ingest/`:
  - `backfill_season(year)` — wraps pybaseball with retries, chunk by month
  - `incremental(yesterday)` — delta pull
  - `normalize_pitch_row()` — standard pitch types, zone buckets
- CLI: `scripts/mlb_statcast_backfill.py --start-year 2015 --end-year 2025`
- S3 layout + manifest file per season
- Admin enqueue + GH workflow `workflow_dispatch` for backfill

**Exit criteria**

- 2018–2025 seasons in S3 (pilot); row counts within ~5% of Savant published totals.
- Idempotent reruns (skip existing partitions).

---

### Phase 2 — Profile builder (2–3 weeks)

**Deliverables**

- `profile_builder.py`:
  - Aggregate from parquet → batter/pitcher tensors for windows `7d`, `30d`, `season`, `3yr_decay`
  - Write snapshots to Postgres
- `shrinkage.py`:
  - League priors per pitch type
  - Reliability = `n / (n + k)` with sport-tuned `k` (e.g. 200 pitches for whiff%)
- Unit tests on synthetic pitch DataFrames

**Exit criteria**

- For 2025-05-25 slate, ≥90% of probable batters/pitchers have `reliability > 0` on top 3 pitch types.
- Spot-check: cutter-heavy LHP vs FB-inside batter → positive K delta vs league.

---

### Phase 3 — Strikeout integration (1–2 weeks)

**Deliverables**

- Replace live `fetch_*` in hot path with `ProfileStore.get_pitcher(id, as_of)` / `get_batter(id, hand, as_of)`.
- `lineup_matchup_adjusted_strikeouts` uses reliability-weighted tensors; never skip lineup—fall back to archetype.
- Log `matchup_source`: `observed | shrunk | archetype | league`.
- Backtest hook: `scripts/mlb_backtest.py --use-profiles` with point-in-time snapshots.

**Exit criteria**

- Backtest vs baseline (no profiles): K projection MAE or Brier on O/U improves or neutral on 2023–2024 holdout.
- Daily cron produces same or better strikeout row count; latency within +10% of today.

---

### Phase 4 — Hits / HR / boards (2 weeks)

**Deliverables**

- Extend tensors: `xwoba`, `iso`, `barrel_rate` per pitch type for batters.
- `daily_batter_projection.py` + `hits.py`: contact-quality matchup factor (not only whiff).
- HR path: align `dingerParlay` power features with profile store (single source).

**Exit criteria**

- Projected hits board shows `profile_version` metadata.
- HR model optional input: `matchup_contact_score`.

---

### Phase 5 — Game MC: lineup-weighted lambdas (1–2 weeks)

**Deliverables**

- `expected_runs_from_lineup(home_lineup, away_lineup, pitcher_profiles)` using profile matchup loop.
- Plug into `enrich_predictions_with_monte_carlo` before sim (replace heuristic mus when lineup known).
- Store `sim_distribution.matchup_meta` (avg reliability, archetype %).

**Exit criteria**

- Game backtest: total MAE or O/U calibration not worse than current MC; prefer improvement on high-lineup-confidence games.

---

### Phase 6 — Archetypes & similarity (2 weeks, optional parallel)

**Deliverables**

- Offline cluster job on Statcast rolling features.
- `mlb_player_archetypes` table; assign ID map each season.
- Cold-start: map debut players to archetype priors within 14 days.

**Exit criteria**

- Rookies (<50 PA) get non-zero matchup adjustment vs all pitcher types.

---

### Phase 7 — PA-level sim pilot (4–6 weeks, PRD-aligned)

**Deliverables**

- Simplified PA generator: draw pitch type from usage → outcome from batter posterior (K/BB/BIP).
- 9-inning loop, bullpen stub, park factor.
- Separate from production game MC until backtest sign-off.

**Exit criteria**

- Prop correlation sanity vs empirical; runtime <60s/game at 10k sims.

---

### Phase 8 — Production hardening (ongoing)

- Monitoring: profile coverage %, ingest lag, matchup delta distribution
- `prod_verify_mlb_profiles.py` alongside Monte Carlo verify
- Docs: `docs/MLB_MATCHUP_PROFILES.md`
- Promotion playbook entry in `ML_PROMOTION.md`

---

## 6. Approach options (decision record)

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **A. Statcast warehouse + Postgres aggregates** (recommended) | Reproducible backtest; fast daily reads; aligns with existing S3 HR path | Upfront backfill ops | **Ship** |
| **B. Live API only + caching** | Less infra | No deep history; rate limits; poor backtest | Reject |
| **C. Buy third-party tensors** | Fast | Cost, lock-in, less control | Defer |

**Shrinkage:** Empirical Bayes v1; PyMC/Stan v2 only if backtest plateaus.

---

## 7. Success metrics

| Metric | Target (vs current baseline) |
|--------|------------------------------|
| Profile coverage (slate batters with reliability>0.3 on top-3 pitches) | ≥95% mid-season |
| Strikeout MAE / line O-U Brier | ≥2% relative improvement 2023–24 backtest |
| Hit/HR board hit rate | Neutral or +1–2 pp |
| Game total MAE | Neutral or improved when lineup confirmed |
| Pipeline SLA | Profile rebuild <30 min; incremental ingest <15 min |
| Zero silent skip | 0% lineup batters with `matchup_source=none` |

---

## 8. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Statcast rate limits / gaps | Monthly chunks; retry; 2015–2017 optional second pass |
| Storage cost | Parquet + column prune; drop raw after aggregates validated |
| Lineup uncertainty pre-game | Weight by `lineup_confidence`; update on confirmed lineups (second beat) |
| Overfitting archetypes | Holdout seasons; minimum cluster stability |
| Worker memory on rebuild | Stream parquet; batch by team or player partition |
| Leakage in backtest | Enforce `as_of_date` on all aggregates |

---

## 9. Dependencies

- `pybaseball` / Statcast access (already in HR tooling)
- S3 bucket policy (`yetibets/mlb/statcast/`)
- Celery worker RAM for profile job (consider dedicated queue)
- Alembic migration on production (Database Migrations workflow)
- No frontend required for v1; API can expose `matchup_meta` later

---

## 10. Timeline summary

| Phase | Calendar (indicative) | Cumulative |
|-------|----------------------|------------|
| 0 Schema | Week 1 | 1 w |
| 1 Statcast backfill | Weeks 2–4 | 4 w |
| 2 Profile builder | Weeks 4–6 | 6 w |
| 3 Strikeouts | Weeks 6–7 | 7 w |
| 4 Hits/HR | Weeks 8–9 | 9 w |
| 5 Game MC | Weeks 10–11 | 11 w |
| 6 Archetypes | Weeks 8–10 (parallel) | — |
| 7 PA sim pilot | Weeks 12–17 | 17 w |
| 8 Hardening | Continuous | — |

**First production value:** end of Phase 3 (~7 weeks) — strikeout props with historical profiles.  
**Full prop stack:** ~9 weeks.  
**PRD Module 6 PA sim:** Phase 7+.

---

## 11. Immediate next steps (after approval)

1. Approve schema + S3 layout in this doc.
2. Create beads issues per phase (`bd create` × 8).
3. Implement Phase 0 migration + `MLB_PROFILES_ENABLED` flag.
4. Run pilot backfill: 2024 season only → validate aggregates vs MLB API splits.
5. Phase 2 point-in-time snapshot for one backtest week before strikeout integration.

---

## 12. Open questions (resolve before Phase 1)

1. **Backfill depth:** 2015 vs 2018 start? (2018 = Statcast quality stabilizes; saves ~3 seasons ingest.)
2. **Postgres vs S3-only aggregates:** Is API latency OK reading profiles from PG only? (Recommended: PG snapshots, S3 raw.)
3. **Second daily run on confirmed lineups?** (Recommended: lightweight 14:00 ET profile-only refresh when lineups post.)

---

*Review this spec before implementation. Next step per superpowers flow: `writing-plans` skill for Phase 0–1 task breakdown.*
