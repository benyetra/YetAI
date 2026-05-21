# WNBA ETL Parity Checklist

Implementation status of WNBA ETL relative to the NBA pipeline.

**Spec:** [`docs/superpowers/specs/2026-05-21-wnba-support-design.md`](../../docs/superpowers/specs/2026-05-21-wnba-support-design.md)
**Plan A (Phase 1):** [`docs/superpowers/plans/2026-05-21-wnba-phase-1.md`](../../docs/superpowers/plans/2026-05-21-wnba-phase-1.md)
**Plan B (Phase 2):** to be written after Plan A ships (tracked as beads issue `YetAI-ejh`)

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
| `totals_projector.py` | `wnba/totals_projector.py` | ✅ done |
| *(none — beyond NBA parity)* | `wnba/spread_projector.py` (Elo + pace) | ✅ done |
| `store_actuals.py` | `wnba/store_actuals.py` (totals + spread) | ✅ done |
| `totals_accuracy_tracker.py` | `wnba/totals_accuracy_tracker.py` | ✅ done |
| *(none — beyond NBA parity)* | `wnba/spreads_accuracy_tracker.py` | ✅ done |

## Phase 2 deliverables — player props (deferred to Plan B)

| NBA file | WNBA equivalent | Status |
|---|---|---|
| `update_recent_games.py` | `wnba/update_recent_games.py` | ⏳ deferred |
| `update_expected_minutes.py` | `wnba/update_expected_minutes.py` | ⏳ deferred |
| `today_active_players.py` | `wnba/today_active_players.py` | ⏳ deferred |
| `_feature_engineering.py` | `wnba/_feature_engineering.py` | ⏳ deferred |
| `_ml_predict.py` | `wnba/_ml_predict.py` | ⏳ deferred |
| `generate_points_predictions.py` | `wnba/generate_points_predictions.py` | ⏳ deferred |
| `generate_assists_predictions.py` | `wnba/generate_assists_predictions.py` | ⏳ deferred |
| `generate_rebounds_predictions.py` | `wnba/generate_rebounds_predictions.py` | ⏳ deferred |
| `calculate_prediction_accuracy.py` | `wnba/calculate_prediction_accuracy.py` | ⏳ deferred |
| *(none — one-shot script)* | `wnba/backfill_wnba_history.py` | ⏳ deferred |

Phase 2 schema tables (7) were created up-front in the Plan A migration so Plan B
needs no schema changes.

## Beyond-NBA-parity items

Two pieces of the Phase 1 build do not exist in NBA. Backports tracked as beads
issues:

1. **`spread_projector.py` — own spread/win-probability model.** Elo rating per
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
| `wnba-update-pipeline-daily` | 03:00 ET daily |
| `wnba-update-game-lines-every-30m` | every 30 min |
| `wnba-update-injuries-every-2h` | every 2 h |
| `wnba-projectors-pregame-hourly` | hourly 09:00–22:00 ET |
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

- `update_team_roster`: **15 teams, 179 players** (incl. 13 active + 2 expansion placeholders for Toronto Tempo / Portland Fire)
- `update_team_offense_stats` / `_defense_stats`: 15 teams each, joined Base + Defense + Advanced dashboards
- `update_injury_status`: **36 of 38 ESPN injury rows matched** to roster; 2 unmatched are players not yet on any team's stats.wnba.com roster (acceptable, logged at INFO)
- `store_actuals`: 3 of 3 completed games from 2026-05-20 ingested into both totals_actuals and spread_actuals
- `totals_projector` / `spread_projector`: ran clean, produced 0 projections (no `pred_wnba_game_lines` rows present yet — gated on real ODDS_API_KEY)
- `update_game_lines`: 401 on placeholder ODDS_API_KEY (expected in dev); will resolve on staging/prod where a real key is set

## Configuration

- `ODDS_API_KEY` env var must be set for `update_game_lines` to populate.
- `LeagueDashTeamStats` and `LeagueDashPlayerStats` in nba_api use the
  `league_id_nullable` kwarg (not `league_id`). Pinned to `"10"` for WNBA in
  `wnba/_wnba_stats.py`.
- WNBA stats.wnba.com season format is a single calendar year string (e.g.
  `"2025"`, `"2026"`). This differs from the NBA's `"2025-26"` format. Encoded
  in `wnba/update_team_roster.py:_current_season()` etc.
