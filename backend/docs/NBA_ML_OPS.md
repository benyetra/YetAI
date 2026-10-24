# NBA ML operations

## Prop calibration (BKB-2.6)

Holdout residual quintiles on projected value → `P(actual > line)` via normal
approximation per bucket. Fitted during `run_train_props` and stored in model
metadata as `prop_calibration`.

**Gate:** every holdout bucket with ≥5 rows must have `|residual_mean| < 0.3`
(residual = `pred - actual`). When the gate fails, `passes_gate` is false and
inference does not attach `p_over`.

**Enable at inference** (default off):

```bash
export NBA_PROP_CALIBRATION_ENABLED=1
```

Requires `fanduel_line` on the projection row and stable calibration in
`xgb_<stat>_metadata.json` (`prop_calibration.passes_gate: true`).

`p_over` is written to `row.factors["p_over"]` when a `factors` JSON column
exists; otherwise attachment is a no-op until a column is added.

**Train + refresh metadata:**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m app.services.etl.nba.ml_training.run_train_props \
  --stat points --season-start 2024-10-01 --season-end 2026-06-30 --upload
```

**Tests:**

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nba_prop_calibration.py -q
```

See also `docs/NBA_ETL_PARITY.md` for ETL task mapping.

## Season rollover (each October)

1. Add the new opening night to `REGULAR_SEASON_START` in
   `app/services/etl/nba/_season.py` (fallback: Tuesday on/after Oct 18).
   July 1 → the day before opening night is treated as offseason:
   `update_recent_games` never stores those box scores (Summer League,
   preseason), so rolling averages carry over from last season's games.
2. Verify production data, then repair anything it flags:

   ```bash
   cd backend
   PYTHONPATH=. .venv/bin/python scripts/nba_season_rollover_repair.py verify
   PYTHONPATH=. .venv/bin/python scripts/nba_season_rollover_repair.py purge-offseason --apply
   ```

   `verify` diffs `pred_team_roster` against ESPN's live rosters (missing
   players, wrong teams, synthetic ids) and counts offseason rows.
3. Retrain on the last two full seasons once the data is clean (workflow
   defaults: `--start 2024-10-01 --end 2026-06-30`) via **NBA Train Prop
   Models** / **NBA Train Spread Model**. The spread model and spread Elo
   both read `pred_nba_spread_actuals`; if a season is missing there,
   backfill it from ESPN first (dry run without `--apply`, or the
   `backfill-spread-actuals` action of **NBA Season Ops**):

   ```bash
   PYTHONPATH=. .venv/bin/python scripts/nba_backfill_spread_actuals.py \
     --from 2024-10-22 --to 2026-06-30 --apply
   ```

**Spread model gate.** The spread XGBoost replaces the Elo margin entirely,
so `train_spread_model` uploads only when its holdout MAE beats Elo on the
same split (`baseline_test_mae` in the metadata; status `below_baseline`
otherwise), and `_spread_ml_predict` ignores any S3 model whose metadata
lacks that win. Features are point-in-time from `pred_nba_spread_actuals`
(Elo, last-10 form, rest/back-to-back) plus the market line (NaN when
missing), so past seasons train on what the projector sees live. Daily
actuals come from ESPN (`store_spread_actuals`).

**Player ids.** `resolve_nba_player_id` matches accent-, case- and
suffix-insensitively against nba_api's static list (stale for each new draft
class — NBA.com blocks cloud IPs, so there is no live lookup). Unmatched
players get `SYNTHETIC_ID_BASE + api_sports_id` so rookies still flow
through the pipeline; pin real ids in `MANUAL_PLAYER_IDS` when known (the
test suite checks every pin against nba_api).

**Rosters.** `update_team_roster` uses ESPN's live rosters as the
tie-breaker for team assignment (trades, signings) and refuses to replace
the table with an incomplete roster (< 300 players or < 25 teams).

## Honest evaluation and the daily loop

- **Holdout is chronological.** Prop and spread models train on the first 80% of
  rows (builders emit them in date order) and are judged only on the last 20%.
  The old check scored the model on every row, including the ones it trained
  on, and used a random split; that is why retrain reported a 4.1 points MAE
  while live points were 5.2. Props must also beat a player's recent average
  (5/10/20-game) on the same holdout; the spread must beat Elo. The spread
  predictor ignores any uploaded model that was not validated chronologically.
- **Totals** are projected from final scores (`totals_baseline.py`): last
  season weighted, this season blended in after two weeks, plus a shrunk
  average of the baseline's last 30 errors. Calls need 4+ points of edge and
  their confidence is the measured hit rate; calls stop if that record is
  below -110 breakeven after 30 graded picks.
- **Refresh before tip-off.** `nba-pregame-refresh` (12:00 and 17:00 ET) updates
  injuries and lines and re-runs every projector, since books post props after
  the 3:30 ET run. Set `NBA_PREGAME_REFRESH_ENABLED=0` to stop it (it spends
  Odds API credits).
- **Scorecard.** `NBA Daily Scorecard` (9:30 ET) posts the totals backtest and
  the prop audit to its run summary. `NBA Weekly Retrain` (Mon 11:00 UTC)
  retrains spread and points/rebounds/assists; a model that fails its gate is
  a warning and the live model stays.
- Read-only checks: Season Ops `backtest-totals`, `audit-props`, `debug-totals`.
