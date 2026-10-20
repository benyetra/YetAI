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
   Models** / **NBA Train Spread Model**.

**Player ids.** `resolve_nba_player_id` matches accent-, case- and
suffix-insensitively against nba_api's static list (stale for each new draft
class — NBA.com blocks cloud IPs, so there is no live lookup). Unmatched
players get `SYNTHETIC_ID_BASE + api_sports_id` so rookies still flow
through the pipeline; pin real ids in `MANUAL_PLAYER_IDS` when known (the
test suite checks every pin against nba_api).

**Rosters.** `update_team_roster` uses ESPN's live rosters as the
tie-breaker for team assignment (trades, signings) and refuses to replace
the table with an incomplete roster (< 300 players or < 25 teams).
