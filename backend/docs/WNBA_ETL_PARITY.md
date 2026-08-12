# WNBA ETL Parity Checklist

Implementation status of WNBA ETL relative to the NBA pipeline.

**Spec:** [`docs/superpowers/specs/2026-05-21-wnba-support-design.md`](../../docs/superpowers/specs/2026-05-21-wnba-support-design.md)
**Plan A (Phase 1):** [`docs/superpowers/plans/2026-05-21-wnba-phase-1.md`](../../docs/superpowers/plans/2026-05-21-wnba-phase-1.md)
**Plan B (Phase 2):** [`docs/superpowers/plans/2026-05-21-wnba-phase-2.md`](../../docs/superpowers/plans/2026-05-21-wnba-phase-2.md) — shipped; beads `YetAI-ejh` closed

## Phase 1 deliverables — game lines

| NBA file | WNBA equivalent | Status |
|---|---|---|
| `_espn.py` | `wnba/_espn.py` | ✅ done |
| `_api_sports.py` | `wnba/_wnba_stats.py` (nba_api `league_id_nullable="10"`) | ✅ done |
| *(N/A — generated)* | `wnba/_team_id_map.py` | ✅ done |
| `update_team_roster.py` | `wnba/update_team_roster.py` | ✅ done |
| `update_team_offense_stats.py` | `wnba/update_team_offense_stats.py` | ✅ done |
| `update_team_defense_stats.py` | `wnba/update_team_defense_stats.py` | ✅ done |
| `update_injury_status.py` | `wnba/update_injury_status.py` (ESPN feed) | ✅ done |
| `update_game_lines.py` | `wnba/update_game_lines.py` (consensus-only) | ✅ done |
| *(historical odds)* | `wnba/historical_game_lines.py` + `scripts/backfill_wnba_historical_game_lines.py` | ✅ done |
| `totals_projector.py` | `wnba/totals_projector.py` | ✅ done |
| *(NBA parity)* | `wnba/totals_ml.py` (residual GBM shadow; `WNBA_TOTALS_ML_ENABLED=1` promotes) | ✅ done |
| *(NBA parity)* | `wnba/ml_training/train_totals_model.py` + `build_totals_dataset.py` | ✅ done |
| *(none — beyond NBA parity)* | `wnba/spread_projector.py` (ML when S3 `xgb_spread`, else Elo+pace) | ✅ done |
| `store_actuals.py` | `wnba/store_actuals.py` (totals + spread) | ✅ done |
| `totals_accuracy_tracker.py` | `wnba/totals_accuracy_tracker.py` | ✅ done |
| *(none — beyond NBA parity)* | `wnba/spreads_accuracy_tracker.py` | ✅ done |

## Phase 2 deliverables — player props (live)

| NBA file | WNBA equivalent | Status |
|---|---|---|
| `update_recent_games.py` | `wnba/update_recent_games.py` | ✅ done |
| *(shared)* | `wnba/_boxscore_fetch.py` | ✅ traditional + BoxScoreAdvancedV2 merge |
| *(one-shot)* | `scripts/backfill_wnba_shooting_columns.py` | ✅ SQL eFG/TS backfill on historical rows |
| `update_expected_minutes.py` | `wnba/update_expected_minutes.py` | ✅ done (NBA-weighted recency + B2B/home + teammate-out boost) |
| *(shared)* | `wnba/_expected_minutes.py` | ✅ `calc_metrics` + context + historical teammate-out (box-score absences) |
| `today_active_players.py` | `wnba/today_active_players.py` | ✅ done |
| `_feature_engineering.py` | `wnba/_feature_engineering.py` | ✅ done (historical `expected_minutes` + teammate-out via `_training_context`) |
| `_ml_predict.py` | `wnba/_ml_predict.py` | ✅ done |
| `generate_points_predictions.py` | `wnba/generate_points_predictions.py` | ✅ done |
| `generate_assists_predictions.py` | `wnba/generate_assists_predictions.py` | ✅ done |
| `generate_rebounds_predictions.py` | `wnba/generate_rebounds_predictions.py` | ✅ done |
| `calculate_prediction_accuracy.py` | `wnba/calculate_prediction_accuracy.py` | ✅ done |
| *(one-shot)* | `wnba/backfill_wnba_history.py` | ✅ done |
| *(one-shot)* | `wnba/backfill_wnba_sportsdataverse.py` + `cache_wnba_player_ids.py` | ✅ done (ESPN parquet; player-id cache in `app/data/wnba_player_id_cache/`) |
| *(training)* | `wnba/_training_context.py` + optimized `ml_training/build_training_dataset.py` | ✅ done (bulk preload; ~3s vs ~90min per stat over Railway) |
| Phase 3 props | `generate_three_pt_made_predictions` + `generate_pra_predictions` | ✅ 3PM XGB + PRA derived (P+R+A×0.98) |

Phase 2 schema tables (7) were created up-front in the Plan A migration so Plan B
needs no schema changes.

## Historical data (2026-06-06, prod)

One-shot backfills completed on production DB:

| Table | Source | Coverage |
|---|---|---|
| `pred_wnba_recent_games` | SportsDataverse ESPN parquet (`backfill_wnba_sportsdataverse`) | **~25.5k** player-games, 2021-05-14 → 2026-06-05 |
| `pred_wnba_game_lines` | Odds API historical + live (`historical_game_lines` + `update_game_lines`) | **231** snapshot dates; fetch-once log (`pred_wnba_game_lines_fetch_log`) — dry-run shows **0** dates left to fetch |

Prop training window 2024-05-01 → 2025-12-31 yields **~9k** feature rows per stat after lookback filtering.

## Phase 2 prop model MAE gates

All three XGBoost prop models passed training-time MAE gates and were uploaded to
`s3://yetibets/wnba/ml_models/xgb_{points,assists,rebounds}.pkl`.

**Prior baseline (2026-05, 42-feature set, no Vegas):**

| Model | Validation MAE | Gate | Status |
|---|---|---|---|
| Points | **4.261** | 4.5 | ✅ pass |
| Assists | **1.266** | 1.5 | ✅ pass |
| Rebounds | **1.829** | 2.0 | ✅ pass |

**Retrain (2026-06-06, expanded features + Vegas context + historical box scores):**
Training window `2024-05-01` → `2025-12-31`. Feature set adds volatility, trend,
matchup, shooting volume, expected-minutes replay, and Vegas fields
(`market_total`, `market_spread`, `is_home`, `is_favorite`). Dataset build uses
`_training_context` bulk preload (~3s/stat vs ~90min N+1 over Railway).

| Model | Rows | Validation MAE | Gate | Test MAE | Status |
|---|---|---|---|---|---|
| Points | 9,129 | **2.94** | 4.5 | 4.17 | ✅ pass |
| Assists | 9,035 | **0.87** | 1.5 | 1.28 | ✅ pass |
| Rebounds | 9,035 | **1.28** | 2.0 | 1.80 | ✅ pass |

Retrain commands:

```bash
# Holdout eval (needs DATABASE_URL)
cd backend && PYTHONPATH=. .venv/bin/python \
  -m app.services.etl.wnba.ml_training.prop_model_eval \
  --stat points --train-start 2024-05-01 --holdout-start 2025-05-01 --holdout-end 2025-12-31

# Train + upload (GitHub Actions: WNBA Train Prop Models, or locally)
cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.ml_training \
  --stat points --start 2024-05-01 --end 2025-12-31 --upload
# Repeat for assists, rebounds
```

## Spread ML model quality

Spread margin model: `s3://yetibets/wnba/ml_models/xgb_spread.pkl`. Trained via
`train_spread_model` on games with both `pred_wnba_spread_actuals` and matching
`pred_wnba_game_lines` (includes `market_spread_home`, `market_total`).

**Unlike prop models, spread training has MAE + Brier upload gates** — `--upload`
is blocked when holdout fails (`status: gate_failed`) unless `--skip-gate`.
Runtime also refuses ML when metadata fails the gate (falls back to Elo+pace);
override with `WNBA_SPREAD_ML_FORCE=1`.

| Gate | Threshold |
|---|---|
| Holdout margin MAE | ≤ **9.0** |
| Holdout win-prob Brier | ≤ **0.28** |

| Run | Rows | Train MAE | Test MAE | Notes |
|---|---|---|---|---|
| 2026-06-06 (post lines backfill) | **602** | **1.68** | **11.42** | Uploaded before gates; **fails gate** → Elo at runtime |
| 2026-06-06 (first upload, partial lines) | 602 | 2.04 | 11.21 | Superseded |

**Production behavior:** `spread_projector.py` uses the S3 model only when loadable
**and** `passes_quality_gate()` (`projection_method = "ml"`); otherwise **Elo + pace**
(`elo_pace`).

**Quality assessment:** Test MAE ~**11.4** vs train ~**1.7** indicated severe
overfitting on **602** games. Gates now block re-upload and force Elo until a
passing model is trained.

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.ml_training.train_spread_model \
  --start 2021-05-01 --end 2025-12-31 --upload
```

## Totals ML model quality

Totals residual model: `s3://yetibets/wnba/ml_models/gbm_totals_residual.pkl`. Trained via
`train_totals_model` on games with `pred_wnba_totals_actuals` (or spread-derived actuals)
and heuristic features from stored projections or point-in-time pace/efficiency replay.

**MAE gate:** holdout **residual** MAE ≤ **1.0** on a time-based split (last 20% of game
dates). `--upload` is blocked when the gate fails (`status: gate_failed`). Ops override:
`--skip-gate`. Metadata also reports heuristic vs ML **full-total** holdout MAE and
**segmented** holdout metrics under ``holdout.segments``:
``with_market_total`` vs ``without_market_total`` (split on stored ``market_total`` feature).

**Production behavior:** `totals_projector.py` always runs the heuristic baseline, then
`totals_ml.enrich_projection()` attaches `ml_shadow` in `factors`. Production
`projected_total` stays heuristic unless `WNBA_TOTALS_ML_ENABLED=1` and S3 load
succeeds.

Before training, sync totals actuals, historical game lines, stored projections, and
attach market lines to projections (train/serve alignment):

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.backfill_spread_actuals \
  --source spread --start 2021-05-01 --end 2025-12-31
# Historical odds (~30 credits/date); skip dates already in fetch log
cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.backfill_historical_game_lines \
  --start 2021-05-01 --end 2025-12-31
cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.ml_training.backfill_totals_projections \
  --start 2021-05-01 --end 2025-12-31
cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.ml_training.backfill_totals_projections \
  --start 2021-05-01 --end 2025-12-31 --sync-markets-only
cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.ml_training.train_totals_model \
  --start 2021-05-01 --end 2025-12-31 --upload
```

After adding game lines without replaying pace/form, run ``--sync-markets-only`` only.
After changing team-stats lookback or projection logic, re-run full backfill with ``--force``.

Train output includes ``dataset_stats`` with ``stored_projections`` vs ``fast_replay`` counts.
Prefer **stored_projections ≈ rows** before trusting holdout MAE; high ``fast_replay`` means
train/serve skew remains.

GitHub Actions: **WNBA Train Totals Model** (`workflow_dispatch`). Upload step fails if
the MAE gate is not met.

## Production go-live checklist (2026-06-06)

| Check | Status |
|---|---|
| Prod DB migrations through `20260606_wnba_fetch_log` | ✅ applied |
| Historical box scores (`pred_wnba_recent_games`) | ✅ ~25.5k rows (2021–2026) |
| Historical game lines (`pred_wnba_game_lines`) | ✅ backfill complete (231 dates, 0 pending) |
| `GET https://api.yetai.app/health` — DB + scheduler + `ODDS_API_KEY` | ✅ verified |
| `GET https://yetai.app/predictions/wnba` | ✅ 200 (page shell) |
| `/api/v1/predictions/wnba` | Requires paid auth — verify logged-in in app |
| Celery Beat — **8** WNBA entries in `celery_app.py` | ✅ verified via `verify_wnba_prod_go_live.py` |
| S3 models `s3://yetibets/wnba/ml_models/*.pkl` | ✅ props + spread uploaded (2026-06-06) |

Local verifier:

```bash
cd backend && python3 scripts/verify_wnba_prod_go_live.py
```

## Phase 2 live smoke (2026-05-22)

End-to-end orchestrator run with all Phase 1 + Phase 2 steps. Roster dedupe +
`UNIQUE(team_id, player_id)` migration `f8a2c91e04bd` applied on prod. The prop
pipeline returned:

```
today_active_players  : {games: 3, players: 104}
update_expected_minutes: {players_updated: 65, players_skipped_thin_data: 39}
generate_points       : {projections_written: 78, skipped_injured: 9, skipped_thin_history: 17}
generate_assists      : {projections_written: 78, skipped_injured: 9, skipped_thin_history: 17}
generate_rebounds     : {projections_written: 78, skipped_injured: 9, skipped_thin_history: 17}
prop_accuracy         : {actuals_written: 183}
```

Top-10 projected scorers for 2026-05-22:

| Player | Opponent | Projected pts |
|---|---|---|
| Kelsey Mitchell | Golden State Valkyries | 24.9 |
| Rhyne Howard | Dallas Wings | 21.5 |
| Allisha Gray | Dallas Wings | 21.1 |
| Paige Bueckers | Atlanta Dream | 18.1 |
| Tina Charles | Seattle Storm | 16.4 |
| Janelle Salaun | Indiana Fever | 15.8 |
| Aliyah Boston | Golden State Valkyries | 15.3 |
| Marina Mabrey | Seattle Storm | 15.1 |
| Angel Reese | Dallas Wings | 14.3 |
| Arike Ogunbowale | Atlanta Dream | 13.7 |

Top assists samples: Veronica Burton 7.8, Rhyne Howard 6.3, Paige Bueckers 5.2.
Top rebounds samples: Jessica Shepard 9.7, Aliyah Boston 9.4, Naz Hillmon 9.0.

## Upsert hygiene (2026-05-22)

All WNBA ETL writers use `app/services/etl/wnba/_db_upsert.py`:

- `upsert_many()` — `INSERT ... ON CONFLICT DO UPDATE` for tables with a unique
  constraint on natural keys (roster, game lines, projections, recent games, etc.)
- `replace_matching()` — delete-then-insert for accuracy summary tables keyed by
  `(date_range_start, date_range_end)` (no unique index on those windows)

`totals_projector.py` already used query-then-update for `pred_wnba_totals_projections`.

## Beyond-NBA-parity items

Two pieces of the Phase 1 build do not exist in NBA. Backports tracked as beads
issues:

1. **`spread_projector.py` — spread/win-probability model.** Uses XGBoost margin
   model (`s3://yetibets/wnba/ml_models/xgb_spread.pkl`) when uploaded; falls back
   to Elo+pace. Train: `python -m app.services.etl.wnba.ml_training.train_spread_model
   --start YYYY-MM-DD --end YYYY-MM-DD [--upload]`. See **Spread ML model quality**
   above — current test MAE ~11.4 with no upload gate. Elo rating per team replayed
   from `pred_wnba_spread_actuals`, plus pace/efficiency overlay, plus WNBA HCA =
   2.5. NBA currently has only `totals_projector`. Backport tracked as **YetAI-q9z**.

2. **Consensus-average market line storage in `pred_wnba_game_lines`** (vs NBA's
   per-book rows in `pred_nba_game_lines`). Plan A stores a single row per game
   with mean across books. If the UI grows a "best line" feature, this needs
   re-evaluation — tracked as **YetAI-egl**.

## Cron / beat schedule

All WNBA jobs are season-gated (May 1 – October 31 Eastern) inside the task body;
outside the window they return `{"status": "out_of_season"}` without touching the
DB or any external API.

| Beat entry | Schedule |
|---|---|
| `wnba-update-pipeline-daily` | 03:00 ET daily (no Odds API lines; uses `pred_wnba_game_lines`) |
| `wnba-update-game-lines-thrice-daily` | 06:10 / 14:10 / 22:10 ET (Odds API cap) |
| `wnba-update-injuries-every-2h` | every 2 h |
| `wnba-update-team-stats-daily` | daily (team offense/defense dashboards) |
| `wnba-projectors-pregame-hourly` | hourly 09:00–22:00 ET (same orchestrator; no Odds line refresh) |
| `wnba-store-actuals-morning` | 04:00 ET daily |
| `wnba-totals-accuracy-morning` | 05:00 ET daily |
| `wnba-spreads-accuracy-morning` | 05:10 ET daily |

## Schema strategy

Parallel `pred_wnba_*` tables. No discriminator column on existing NBA tables —
WNBA and NBA player/team IDs are in different namespaces (stats.wnba.com numeric
IDs in the 1611661xxx range; verified live during Plan A smoke), so there is no
risk of cross-league collision in the parallel scheme. Unification under a
`league` discriminator is tracked as **YetAI-4sa** for future evaluation if
maintenance cost grows.

## Live smoke verification

T19 smoke against staging (2026-05-21):

- `update_team_roster`: **15 teams, 179 players** (13 legacy + Golden State Valkyries + Toronto Tempo / Portland Fire; expansion stats IDs verified 2026-05-22 as `1611661332` / `1611661327`)
- `update_team_offense_stats` / `_defense_stats`: 15 teams each, joined Base + Defense + Advanced dashboards
- `update_injury_status`: **36 of 38 ESPN injury rows matched** to roster; 2 unmatched are players not yet on any team's stats.wnba.com roster (acceptable, logged at INFO)
- `store_actuals`: 3 of 3 completed games from 2026-05-20 ingested into both totals_actuals and spread_actuals
- `totals_projector` / `spread_projector`: ran clean, produced 0 projections (no `pred_wnba_game_lines` rows present yet — gated on real ODDS_API_KEY)
- `update_game_lines`: 401 on placeholder ODDS_API_KEY (expected in dev); will resolve on staging/prod where a real key is set

## Configuration

- `ODDS_API_KEY` env var must be set for `update_game_lines` to populate.
- Historical consensus lines (spread ML + prop Vegas features): ~30 Odds API credits/date.
- Historical player box scores: run `cache_wnba_player_ids` once per season, then
  `backfill_wnba_sportsdataverse` (no per-game stats.nba.com calls).

  ```bash
  cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.cache_wnba_player_ids \
    --seasons 2021,2022,2023,2024,2025
  cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.backfill_wnba_sportsdataverse \
    --seasons 2021,2022,2023,2024,2025
  ```

  ```bash
  cd backend && PYTHONPATH=. .venv/bin/python scripts/backfill_wnba_historical_game_lines.py \
    --start 2021-05-01 --end 2025-10-01 --dry-run
  cd backend && PYTHONPATH=. .venv/bin/python scripts/backfill_wnba_historical_game_lines.py \
    --start 2021-05-01 --end 2025-10-01 --max-dates 25
  ```

  Historical backfill uses `pred_wnba_game_lines_fetch_log` (fetch-once per snapshot
  date). Run `alembic upgrade head` once before the first backfill on a fresh DB.
  Dates with partial line coverage from earlier runs are auto-seeded into the log so
  unfillable Odds API gaps are not re-fetched every batch.

  ```bash
  cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.update_game_lines
  cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.ml_training.train_spread_model \\
    --start 2021-05-01 --end 2025-12-31 --upload
  cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.ml_training.train_totals_model \\
    --start 2024-05-01 --end 2025-12-31 --upload
  ```
- Totals ML shadow is always attached when the model loads; set `WNBA_TOTALS_ML_ENABLED=1`
  on the API/worker to promote `ml_total` to production `projected_total`. Local override:
  `WNBA_TOTALS_MODEL_LOCAL=/path/to/dir` (expects `gbm_totals_residual.pkl` + metadata).
  Live compare: `totals_accuracy_tracker` writes heuristic vs ML MAE and sets
  `recommend_promote` when season ML MAE beats heuristic (≥20 games). CLI:
  `PYTHONPATH=. .venv/bin/python scripts/wnba_totals_ml_promote_check.py`.
- Prop P(over): train stores `prop_calibration` in XGB metadata; inference attaches
  `factors.p_over` when `WNBA_PROP_CALIBRATION_ENABLED=1` and calibration passes gate.
- Spread ML: upload gated by MAE≤9 / Brier≤0.28; runtime Elo fallback unless metadata
  passes gate (override `WNBA_SPREAD_ML_FORCE=1`).
- Season Elo reseeding: `load_elos_from_actuals` applies
  `0.75 * prior + 0.25 * league_mean` at season boundaries (WNBA May / NBA Oct).
- Backtest harness: `PYTHONPATH=. .venv/bin/python scripts/wnba_backtest.py --quick`
  grades stored ATS / totals / prop ROI at -110.
- Phase 3 props: 3PM (XGB, train `three_pt_made`) + PRA (derived). Tables
  `pred_wnba_{three_pt_made,pra}_{projections,actuals}`. Enable after
  `alembic upgrade head` and uploading `xgb_three_pt_made.pkl`.
- Totals injury impact: usage-weighted from recent box scores (rotation players);
  `STAR_PLAYER_IMPACTS` remains fallback for thin history.
- `LeagueDashTeamStats` and `LeagueDashPlayerStats` in nba_api use the
  `league_id_nullable` kwarg (not `league_id`). Pinned to `"10"` for WNBA in
  `wnba/_wnba_stats.py`.
- WNBA stats.wnba.com season format is a single calendar year string (e.g.
  `"2025"`, `"2026"`). This differs from the NBA's `"2025-26"` format. Encoded
  in `wnba/update_team_roster.py:_current_season()` etc.
