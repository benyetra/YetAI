# NFL Anytime Touchdown — ops notes

Hierarchical λ → `P(TD) = 1 - exp(-λ)` for QB/RB/WR/TE. Predictions live in
`pred_nfl_anytime_td_predictions`; grading in `pred_nfl_anytime_td_actuals`.

## Feature build (nflverse)

Projector `run()` without injected `feature_rows` calls
`build_feature_rows_from_nflverse`:

1. `import_weekly_data` — prior-week usage, team scoring proxies, defense TDs allowed.
   If the current (or prior) season parquet 404s, try
   `stats_player_week_{season}.parquet` (maps `team` → `recent_team`), then fall
   back up to 3 seasons and use all prior-season weeks as priors (needed for Week 1).
2. `import_schedules` — REG matchups, kickoff date, roof/wind (requested season)
3. `import_depth_charts` — skill-position **starters** only (`depth_team=1`;
   excludes KR/PR). If depth is empty, top prior-usage QB/RB/WR×3/TE per team.
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

## Pipeline

See `backend/docs/NFL_ETL_PARITY.md` — Celery phase **anytime_td** runs scheme
sync, projector, and Odds attach (`player_anytime_td`) inside the full NFL weekly
pipeline (`run_nfl_update_pipeline`, Beat `nfl-update-pipeline-daily` @ 4:30 ET).

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

Residual GBM calibrator (optional, on by default when artifact exists):

```bash
PYTHONPATH=. python scripts/nfl_anytime_td_train_calibration.py
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

Turn on **only** when `passes_gate` is true **and** env flags are set:

| Surface | Variable | Truthy values |
|---------|----------|----------------|
| Backend helper | `NFL_ANYTIME_TD_UI` | `1`, `true`, `yes`, `on` |
| Frontend board | `NEXT_PUBLIC_NFL_ANYTIME_TD_UI` | `1`, `true`, `yes` |

Default: both off. API still returns `anytime_td_predictions` for admin/backtest;
the predictions page group stays hidden until the frontend flag is set.

## Accuracy dashboard

Daily NFL accuracy includes an **Anytime TD** Brier bucket when actuals exist
(`nfl_accuracy_service.daily_accuracy`).
