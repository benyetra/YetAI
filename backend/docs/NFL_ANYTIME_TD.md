# NFL Anytime Touchdown — ops notes

Hierarchical λ → Poisson `P(TD) = 1 - exp(-λ)` for QB/WR/TE; RBs use Negative
Binomial `P(X≥1) = 1 - (r/(r+λ))^r` with `RB_TD_DISPERSION = 2.0`. Anytime TD
counts rush + rec only (no passing TDs for the QB). Predictions live in
`pred_nfl_anytime_td_predictions`; grading in `pred_nfl_anytime_td_actuals`.

## Feature build (nflverse)

Projector `run()` without injected `feature_rows` calls
`build_feature_rows_from_nflverse`:

1. `import_weekly_data` — prior-week usage, team scoring proxies, defense TDs allowed.
   If the current (or prior) season parquet 404s, try
   `stats_player_week_{season}.parquet` (maps `team` → `recent_team`), then fall
   back up to 3 seasons and use all prior-season weeks as priors (needed for Week 1).
2. `import_schedules` — REG matchups, kickoff date, roof/wind (requested season)
3. `import_depth_charts` — offensive skill depth through board caps
   (`QB:1, RB:2, WR:3, TE:1`; excludes KR/PR). Filtered to the latest ``dt``
   snapshot (same approach as QB starters). Depth ``club_code`` is the TEAM
   source of truth; usage may enrich name/position but does **not** overwrite
   depth team (avoids stale ``recent_team`` from prior-season weekly fallback /
   pre-trade games). Remaining slots fill from prior usage up to the same caps,
   remapping filled players to depth club when present. If depth is empty,
   usage top-N is the whole universe.
4. YAML schemes — opponent cover / man-zone / pressure tags
5. Optional `pred_nfl_game_lines` — implied totals / script multiplier
6. **Injuries** — nflverse injury reports: drop Out/Doubtful (promote depth-2),
   down-weight Questionable (`availability_mult=0.75`)
7. **Snaps / routes** — nflverse `snap_counts` `offense_pct` (GSIS-mapped) replaces
   target_share snap proxy; WR/TE route participation ≈ snap share (RB discounted)
8. **Game lines / weather** — `update_game_lines` upserts the next 14 days of Odds
   slate; projector joins week-matched `pred_nfl_game_lines` (+ optional
   `pred_nfl_weather`) so every board row gets market totals/spreads and weather
9. **Position GBM** — separate residual calibrators for RB / WR+TE / QB
   (`hierarchical_v1_gbm_pos`) when artifact metadata has
   `conversion_rate_family=rz_gl`; otherwise hierarchical only.
   `NFL_ANYTIME_TD_GBM=0` disables; thin week-1 form also skips GBM.

Pure aggregators are unit-tested offline in `test_nfl_anytime_td_feature_assembly.py`.
RZ trips / share / RZ targets / GL carries come from nflverse **PBP** (`yardline_100`
≤ 20 / ≤ 5) when available, with weekly scoring proxies as fallback.
**RBs** use rush + goal-line carry share (not blended RZ touches) and blend
conversion toward PBP `gl_td_rate`; WR/TE use RZ target share and blend toward
PBP `rz_td_rate` when present. **Do not** feed overall season TD/touch into λ
`conversion_rate` — that unit mismatch crushed high-volume RBs (~0.03–0.08) while
leaving sparse TEs near 0.10–0.25 and produced TE-heavy boards capped near ~25%.
Usage stores `td_per_touch` as a diagnostic only; λ conversion uses **depth-
conditioned** RZ/GL priors (RB1 share 0.30 / conv 0.40; RB2 share 0.12 / conv
0.28) plus PBP RZ/GL rates. Missing shares fall back to depth priors so backups
cannot inherit starter-like λ after hierarchical-only inference (#126). Observed
PBP/usage shares for depth≥2 are soft-capped toward the backup prior. Usage
universe keeps top **2 RBs** per team; usage slot-fill assigns `depth_team` by
open slot (not always 1). Depth-club remaps ignore out-of-cap slots (RB3+) to
avoid wrong-team attributions. Walk-forward gate requires beating baseline Brier
(`require_beat_baseline_brier=true`, 0.02 margin) and RB Brier ≤ `max_rb_brier` (0.28).
UI defaults **on** after the 2026-09-04 metrics write (`passes_gate=true`).

## Pipeline

See `backend/docs/NFL_ETL_PARITY.md` — Celery phase **anytime_td** runs scheme
sync, projector, and Odds attach (`player_anytime_td`) inside the full NFL weekly
pipeline (`run_nfl_update_pipeline`, Beat `nfl-update-pipeline-daily` @ 4:30 ET).
Gameday availability (`run_nfl_gameday_availability`) rebuilds the anytime-TD
slate after QB/kicker boards and spread/totals: schemes → projector → betting.

Admin portal (`/admin/pipelines`):

| Catalog entry | Purpose |
|---------------|---------|
| **NFL anytime TD pipeline** | `run_nfl_anytime_td_pipeline` — actuals → schemes → projector → Odds |
| Debug fireables | schemes, projector, Odds attach, actuals, game lines |
| Beat | `nfl-anytime-td-pipeline-midweek` Tue–Fri 11:00 ET |

Enqueue the anytime TD orchestrator for a midweek refresh without re-running QB/kickers.

## Backtest gate (required before UI)

Walk-forward REG seasons (2023–2025 when nflverse weekly is published; auto via
`stats_player_week_{season}.parquet` fallback when legacy `player_stats` 404s).
Offline CI still uses a fixed synthetic `--quick` sample — no DATABASE_URL or Odds.

| Check | Gate |
|-------|------|
| Calibration | Model Brier ≤ `max_brier` (0.25); beat baseline Brier only when market odds present (`require_beat_baseline_brier`) |
| Sample size | `n_graded` ≥ `min_n_graded` (walk-forward default 200; quick default 4) |
| Ranking | Top-20 weekly hit rate ≥ position-prior baseline (walk-forward) |
| Baseline | Market implied when present; else position prior |

Artifact: `backend/models/nfl/anytime_td_metrics.json` (`preset: walk_forward` after live run)

Residual GBM calibrator (optional). Inference applies the on-disk artifact
**only** when metadata stamps `conversion_rate_family=rz_gl` (post-#125 RZ/GL
λ semantics). The 2026-09-04 pickle was trained on overall TD/touch conversion
and is **gated off** until retrain — otherwise it crushes high-λ RBs (OOD
`conversion_rate≈0.38`) and lifts TEs toward the ~27% train base rate. Thin
week-1 rows (null `gl_carries` / `rz_targets`) also skip GBM. Env
`NFL_ANYTIME_TD_GBM=0` disables regardless.

```bash
PYTHONPATH=. python scripts/nfl_anytime_td_train_calibration.py --seasons 2023,2024,2025
# Disable at inference: NFL_ANYTIME_TD_GBM=0
```

```bash
cd backend
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick --write-metrics
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --walk-forward --write-metrics --check-gate
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --season 2024 --start-week 1 --end-week 8
```

## Refresh prod board after TEAM logic changes

TEAM / OPP are denormalized onto `pred_nfl_anytime_td_predictions` at project
time. Deploying this code alone does **not** rewrite existing rows — Odds attach
also preserves team fields.

A successful projector run **upserts** the new slate and **deletes** same
`season`/`week` rows whose `player_id` is not on that slate (`deleted_stale` in
the Celery result). Empty feature builds do **not** purge.

After merge + backend deploy, re-run the ATD projector (schemes → projector →
Odds), e.g.:

- Admin portal → **NFL anytime TD pipeline** (`run_nfl_anytime_td_pipeline`), or
- Wait for Beat: `nfl-update-pipeline-daily` @ 4:30 ET (includes ATD) or
  `nfl-anytime-td-pipeline-midweek` Tue–Fri 11:00 ET

Confirm a previously wrong-team player updates `team_name` /
`opponent_team_name` on the next successful projector upsert (or is removed if
no longer on the slate).

### After conversion-rate / ranking fixes

Deploying λ conversion fixes (reject overall TD/touch, use RZ/GL priors + PBP
rates) does **not** rewrite existing `pred_nfl_anytime_td_predictions` rows.
**Re-run `run_nfl_anytime_td_pipeline` after deploy** so the board re-projects
with corrected `conversion_rate` / P(TD). Odds attach is optional for ranking
(API sorts by `td_probability` only); missing odds leave edges empty/NO_PLAY
but do not reorder the board.

Expected after re-run: starting RBs generally lead by P(TD) (often ~25–40% for
featured backs); **RB2 / clear backups clearly below RB1** (not twin ~30%
clusters like Gibbs≈Vaki or Henry≈Hill); featured TEs mid-board (~10–20%); max
P(TD) no longer clustered on TEs near a ~25% ceiling from prior×inflated-share.

### After depth-prior / backup-RB fixes

Deploying depth-conditioned RZ share + conversion priors does **not** rewrite
existing rows. **Re-run `run_nfl_anytime_td_pipeline` after deploy** so RB1/RB2
separation and corrected teams land on the board.

### After WR anytime-TD prior floor fixes

Post-#128 hierarchical boards left WR1 near ~11% (share 0.18 × conversion 0.20)
while RB1 sat ~30% — under market (~20–35% implied for elite WRs). WR depth
share/conversion priors were raised so WR1 is competitive with (not identical
to) RB1; WR2/WR3 and TE stay below; RB1/RB2 separation from #128 is unchanged.

Deploying these priors does **not** rewrite existing rows. **Re-run
`run_nfl_anytime_td_pipeline` after deploy** so top WRs land in the ~20–28%
neutral band (higher with script/defense).

Optional follow-up: retrain residual GBM
(`scripts/nfl_anytime_td_train_calibration.py`) so calibrators see RZ/GL
`conversion_rate` instead of historical TD/touch values.

### Manual purge (immediate prod relief)

If stale week rows remain before the slate-replace deploy lands, purge rows
older than the latest `prediction_date` for that season/week:

```sql
-- Preview
SELECT player_name, team_name, prediction_date
FROM pred_nfl_anytime_td_predictions
WHERE season = 2026 AND week = 1
  AND prediction_date < (
    SELECT MAX(prediction_date)
    FROM pred_nfl_anytime_td_predictions
    WHERE season = 2026 AND week = 1
  )
ORDER BY player_name;

-- Apply
DELETE FROM pred_nfl_anytime_td_predictions
WHERE season = 2026 AND week = 1
  AND prediction_date < (
    SELECT MAX(prediction_date)
    FROM pred_nfl_anytime_td_predictions
    WHERE season = 2026 AND week = 1
  );
```

Or: `PYTHONPATH=. python scripts/purge_stale_nfl_anytime_td_week.py --season 2026 --week 1 --dry-run`.

If Celery logs show `anytime TD feature build failed` with
`float() argument must be a string or a real number, not 'NoneType'`, the
projector wrote **zero** rows and left stale teams. That crash is fixed by
coercing explicit ``None`` defense/team numerics to priors in
`build_player_feature_row` — redeploy before re-enqueueing.

## Enable UI (prod)

Walk-forward **2026-09-04** (`--seasons 2023,2024,2025`, weeks 2–18, expanding
GBM): `n_graded=8914`, Brier **0.1979** vs baseline **0.196** (within 0.02
margin), top-20 hit rate **46.8%** vs **37.2%** prior, RB Brier **0.2225**
(≤ 0.28). `passes_gate=true`. UI defaults **on**; set flags to `0` to hide.

| Surface | Variable | Truthy values |
|---------|----------|----------------|
| Backend helper | `NFL_ANYTIME_TD_UI` | `1`, `true`, `yes`, `on` (default **1**) |
| Frontend board | `NEXT_PUBLIC_NFL_ANYTIME_TD_UI` | `1`, `true`, `yes`, `on` (unset defaults **on**) |

## Accuracy dashboard

Daily NFL accuracy includes an **Anytime TD** Brier bucket when actuals exist
(`nfl_accuracy_service.daily_accuracy`).
