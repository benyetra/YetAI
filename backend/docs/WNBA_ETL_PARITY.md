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
| *(shared)* | `wnba/_expected_minutes.py` | ✅ `calc_metrics` + context adjustments (live + training) |
| `today_active_players.py` | `wnba/today_active_players.py` | ✅ done |
| `_feature_engineering.py` | `wnba/_feature_engineering.py` | ✅ done (historical `expected_minutes` via `_expected_minutes`; no teammate-out in training) |
| `_ml_predict.py` | `wnba/_ml_predict.py` | ✅ done |
| `generate_points_predictions.py` | `wnba/generate_points_predictions.py` | ✅ done |
| `generate_assists_predictions.py` | `wnba/generate_assists_predictions.py` | ✅ done |
| `generate_rebounds_predictions.py` | `wnba/generate_rebounds_predictions.py` | ✅ done |
| `calculate_prediction_accuracy.py` | `wnba/calculate_prediction_accuracy.py` | ✅ done |
| *(none — one-shot script)* | `wnba/backfill_wnba_history.py` | ✅ done |

Phase 2 schema tables (7) were created up-front in the Plan A migration so Plan B
needs no schema changes.

## Phase 2 model MAE gates

All three XGBoost models passed their training-time MAE gates and were uploaded
to `s3://yetibets/wnba/ml_models/xgb_{points,assists,rebounds}.pkl`:

| Model | Test-set MAE | Gate | Status |
|---|---|---|---|
| Points | **4.261** | 4.5 | ✅ pass |
| Assists | **1.266** | 1.5 | ✅ pass |
| Rebounds | **1.829** | 2.0 | ✅ pass |

**Retrain (2026-06):** Prop feature set expanded (volatility, trend, matchup,
advanced stats, Vegas context). Training replays `historical_expected_minutes()`
per `(player_id, game_date)` using only prior games (recency + B2B/home; live
teammate-out boost remains inference-only). Retrain + S3 upload:

```bash
# Holdout eval (needs DATABASE_URL)
cd backend && PYTHONPATH=. .venv/bin/python \\
  -m app.services.etl.wnba.ml_training.prop_model_eval \\
  --stat points --train-start 2024-05-01 --holdout-start 2025-05-01 --holdout-end 2025-12-31

# Train + upload (GitHub Actions: WNBA Train Prop Models, or locally)
cd backend && PYTHONPATH=. .venv/bin/python -m app.services.etl.wnba.ml_training \\
  --stat points --start 2024-05-01 --end 2025-12-31 --upload
```

Training logs in [`backend/docs/wnba_training_logs/`](./wnba_training_logs/).

## Production go-live checklist (2026-05-22)

| Check | Status |
|---|---|
| Prod DB `alembic_version` = `f8a2c91e04bd` | ✅ migrated via GitHub Actions |
| `GET https://api.yetai.app/health` — DB + scheduler + `ODDS_API_KEY` | ✅ verified |
| `GET https://yetai.app/predictions/wnba` | ✅ 200 (page shell) |
| `/api/v1/predictions/wnba` | Requires paid auth — verify logged-in in app |
| Celery Beat — 7 WNBA entries in `celery_app.py` | ✅ code present; confirm worker+beat deployed on Railway |
| S3 models `s3://yetibets/wnba/ml_models/*.pkl` | Required for prop generators (worker IAM) |

Local verifier:

```bash
cd backend && python scripts/verify_wnba_prod_go_live.py
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
   --start YYYY-MM-DD --end YYYY-MM-DD [--upload]`. Elo rating per
   team replayed from `pred_wnba_spread_actuals`, plus pace/efficiency overlay,
   plus WNBA HCA = 2.5. NBA currently has only `totals_projector`. Backport
   tracked as **YetAI-q9z**.

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

  ```bash
  cd backend && PYTHONPATH=. .venv/bin/python scripts/backfill_wnba_historical_game_lines.py \\
    --start 2021-05-01 --end 2025-10-01 --dry-run
  cd backend && PYTHONPATH=. .venv/bin/python scripts/backfill_wnba_historical_game_lines.py \\
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
  ```
- `LeagueDashTeamStats` and `LeagueDashPlayerStats` in nba_api use the
  `league_id_nullable` kwarg (not `league_id`). Pinned to `"10"` for WNBA in
  `wnba/_wnba_stats.py`.
- WNBA stats.wnba.com season format is a single calendar year string (e.g.
  `"2025"`, `"2026"`). This differs from the NBA's `"2025-26"` format. Encoded
  in `wnba/update_team_roster.py:_current_season()` etc.
