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
3. `import_depth_charts` — skill-position **starters** (`depth_team=1`; excludes
   KR/PR). Remaining slots fill from prior usage up to `{QB:1, RB:2, WR:3, TE:1}`.
   If depth is empty, usage top-N is the whole universe.
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
   (`hierarchical_v1_gbm_pos`); `NFL_ANYTIME_TD_GBM=0` disables

Pure aggregators are unit-tested offline in `test_nfl_anytime_td_feature_assembly.py`.
RZ trips / share / RZ targets / GL carries come from nflverse **PBP** (`yardline_100`
≤ 20 / ≤ 5) when available, with weekly scoring proxies as fallback.
**RBs** use rush + goal-line carry share (not blended RZ touches) and blend
conversion toward GL TD rate; WR/TE use RZ target share. Usage universe keeps
top **2 RBs** per team. Walk-forward gate requires beating baseline Brier
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

Residual GBM calibrator (optional, on by default when artifact exists).
Artifact `anytime_td_residual_gbm.pkl` retrained **2026-09-04** on NegBin
`hier_p` for RBs (`RB_TD_DISPERSION=2.0`; Poisson for other positions):

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
