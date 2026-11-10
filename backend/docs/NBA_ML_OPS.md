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

## Prop picks, features and PRA

- **Pick side.** `fanduel_over_under` is the side of the line the projection
  is on (`_fanduel_lines.pick_side`). The inherited rule called an under only
  when the projection was more than 1.5 below the line and an over otherwise,
  so 17.9 against a 19.5 line was published, graded and auto-picked as an
  over, and threes / rebounds / assists (lines of 1.5-6.5) almost never
  produced an under. Rows written before the fix keep the side they were
  published with; `scripts/nba_props_audit.py` already grades by projection
  side and is the number to compare across the change.
- **Line matching** ignores accents, punctuation and suffixes
  (`normalize_player_name`): "Nikola Jokić" finds "Nikola Jokic".
- **PRA** is points + rebounds + assists with no haircut. The inherited 0.98
  "correlation adjustment" took 2% off every projection; correlation changes
  the spread of a sum, not its mean.
- **Features v3** (`_feature_engineering.FEATURES_VERSION = 3`):
  - `opp_*` come from `_team_defense.team_defense_as_of(opponent, game_date)`,
    the same aggregation `update_team_defense_stats` stores, restricted to
    games before the row's date. Training rows used to read the opponent's
    defense as of the day the dataset was built.
  - The Vegas line is found through the opponent, not through the roster
    table (which only knows a player's team today).
  - New columns: `<stat>_ewm_5/10`, `<stat>_avg_season`, `<stat>_last`,
    `<stat>_per_min_20`, `<stat>_rate_x_min_5/10`, `sample_games`,
    `minutes_avg_3/20/season`, `minutes_ewm_3`, `minutes_last`, and 10/20-game
    shot-volume averages (`fg_attempts`, `three_pt_attempts`, `ft_attempts`,
    `turnovers`, `personal_fouls`).
  - Live models list their own features in metadata, so they keep running on
    the v2 columns until a retrain on v3 passes its gate (**NBA Weekly
    Retrain**, or **NBA Train Prop Models** by hand).

**What v3 buys.** Replayed offline through the same builder and trainer on
public box scores (2024-25, 2025-26 and the first three weeks of 2026-27;
53,255 rows, latest 20% held out, shipped `PROP_HYPERPARAMS`):

| Stat | Recent average (best of 5/10/20) | v2 features | v3 features |
|------|---------------------------------:|------------:|------------:|
| Points | 4.79 | 4.71 | **4.65** |
| Rebounds | 1.91 | 1.90 | **1.87** |
| Assists | 1.41 | 1.37 | **1.36** |

About a third of the gain is the as-of-date opponent defense, the rest the
recency and rate columns. A home/away flag, last season's averages and
opponent-relative-to-league ratios were tried and added nothing. The replay
used ESPN box scores, not the production table, so expect the direction rather
than the exact figures from the first production retrain. Threes, free throws,
steals and blocks were also replayed: a squared-error model does not beat a
recent average on MAE for counts that small, so they are not added to the
weekly retrain and keep their inherited models.

- **Ruled out after the overnight run.** A generator that skips a player for
  injury also deletes his row for today (`_stale_rows`); otherwise the 3:30 ET
  projection, line and pick stay on the board after he is declared out.

## Season rollover (each October)

1. Add the new opening night to `REGULAR_SEASON_START` in
   `app/services/etl/nba/_season.py` (fallback: Tuesday on/after Oct 18).
   July 1 → the day before opening night is treated as offseason:
   `update_recent_games` never stores those box scores (Summer League,
   preseason). Every sample then switches to this season on its own: a
   player's (prop features, expected minutes, PRA, no-steals) as soon as he
   has a game this season (`_samples.player_games`), a team's defense once it
   has one, and the totals baseline once a team has 5
   (`totals_baseline.CURRENT_SEASON`). Last season is only the stand-in when
   there are no current-season games yet.
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

## Game dates in `pred_recent_games`

API-Sports filters `games?date=` by UTC, so a 7 pm ET tip-off comes back under the
next day. Before #173 every box score was filed under the queried (UTC) date: evening
games sat a day late, nightly `store_actuals` matched few projections, and the prop
generators (which read `game_date < today`) skipped the previous night's games. The
ingest now files each game under its Eastern tip-off date.

Rows written before the fix keep their shifted dates. Repair a season with the
**NBA Season Ops** action `repair-recent-game-dates` (inputs `seasons`, `apply`; dry run
unless `apply` is checked), or `scripts/nba_recent_games_date_repair.py`. It copies the
season's rows to `pred_recent_games_bak_<year>`, deletes them and re-pulls every game
day (~1,500 API-Sports calls per full season). Retrain the prop models afterwards.

## Honest evaluation and the daily loop

- **Holdout is chronological.** Prop and spread models train on the first 80% of
  rows (builders emit them in date order) and are judged only on the last 20%.
  The old check scored the model on every row, including the ones it trained
  on, and used a random split; that is why retrain reported a 4.1 points MAE
  while live points were 5.2. Props must also beat a player's recent average
  (5/10/20-game) on the same holdout; the spread must beat Elo. The spread
  predictor ignores any uploaded model that was not validated chronologically.
- **Totals** are projected from final scores (`totals_baseline.py`): this
  season alone once a team has 5 games, last season only before that, plus a
  shrunk average of the baseline's last 30 errors. Calls need 4+ points of
  edge and their confidence is the measured hit rate; calls stop if that
  record is below -110 breakeven after 30 graded picks.
- **Refresh before tip-off.** `nba-pregame-refresh` (12:00 and 17:00 ET) updates
  injuries and lines and re-runs every projector, since books post props after
  the 3:30 ET run. Set `NBA_PREGAME_REFRESH_ENABLED=0` to stop it (it spends
  Odds API credits).
- **Scorecard.** `NBA Daily Scorecard` (9:30 ET) posts the totals backtest and
  the prop audit to its run summary. `NBA Weekly Retrain` (Mon 11:00 UTC)
  retrains spread and points/rebounds/assists; a model that fails its gate is
  a warning and the live model stays.
- Read-only checks: Season Ops `backtest-totals`, `audit-props`, `debug-totals`.
