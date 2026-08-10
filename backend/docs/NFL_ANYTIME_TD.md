# NFL Anytime Touchdown — ops notes

Hierarchical λ → `P(TD) = 1 - exp(-λ)` for QB/RB/WR/TE. Predictions live in
`pred_nfl_anytime_td_predictions`; grading in `pred_nfl_anytime_td_actuals`.

## Feature build (nflverse)

Projector `run()` without injected `feature_rows` calls
`build_feature_rows_from_nflverse`:

1. `import_weekly_data` — prior-week usage, team scoring proxies, defense TDs allowed
2. `import_schedules` — REG matchups, kickoff date, roof/wind
3. `import_depth_charts` — skill-position depth 1–2 (weekly contributors also included)
4. YAML schemes — opponent cover / man-zone / pressure tags
5. Optional `pred_nfl_game_lines` — implied totals / script multiplier

Pure aggregators are unit-tested offline in `test_nfl_anytime_td_feature_assembly.py`.
RZ trips / share are **weekly proxies** until PBP red-zone ETL lands.

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

Walk-forward REG seasons (2023–2025 target in design spec). Offline CI uses a
fixed synthetic sample — no DATABASE_URL or Odds credits.

| Check | Gate |
|-------|------|
| Calibration | Model Brier ≤ `max_brier` (default 0.25) and ≤ baseline Brier + margin |
| Sample size | `n_graded` ≥ `min_n_graded` (default 4) |
| Baseline | Market implied when present; else position prior |

Artifact: `backend/models/nfl/anytime_td_metrics.json`

```bash
cd backend
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick --write-metrics
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick --check-gate
```

Offline regression: `tests/test_nfl_anytime_td_backtest.py`

DB replay (when predictions + actuals exist):

```bash
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
