# NBA player props: review 2026-11-17

Scope: points, rebounds, assists, threes, PRA, steals, blocks, free throws, end to end (box scores,
features, models, retrain, lines, grading, the review scripts, the record gate).
Code is origin/main 5b662edf. Production numbers come only from `.factory/review-1117/evidence/`.

## Bottom line

- The box-score plumbing (#173/#182) looks repaired. New-day numbers from the two scripts now agree
  exactly. The 11-14 retrain holdout MAEs match the "repaired data" numbers in the #182 PR body.
- No NBA prop model beats the line on its own holdout. The retrain loop does not check against the
  line, so it promotes on noise (rebounds went live on 11-16 for a 0.0002 MAE gain while losing to
  the line by 0.075).
- The 1-7 prop record comes mostly from two gaps, not from a broken projection:
  - PRA picks go through with no record gate at all. They were 4 of the 8 prop bets.
  - Rebounds and assists stay open on a record built from the old model, valued at -110, when the
    real price of the side we call is about -125/-128.
- The rising hit rate at bigger rebounds edges (61.6% at edge >= 2) is not evidence of edge. 71 of
  those 73 rows were made before 11-15 by the old, unversioned model. The retrained models produce
  about one such row a day. The new models' own holdouts show a side hit rate of 50.2% (rebounds)
  and 52.3% (assists).

---

## F1. PRA auto picks have no record gate and are measured nowhere (4 of the 8 prop bets)

- **What is wrong**:
  - PRA (`sum-pra-v1` = points + rebounds + assists projections) is a pickable key for YetAI Bets,
    but no projection record exists for it. The record gate can never withhold it until 30 PRA
    bets have settled.
  - Its largest component, points, is itself WITHHELD for a losing record.
  - Users get PRA auto picks built on a points projection the system already judged a loser.
- **Evidence**:
  - `backend/app/services/auto_pick/sources/player_prop_source.py:29` emits PRA from
    `PRAProjections`.
  - `backend/app/services/auto_pick/record_gate.py:249-255` (`_NBA_PROP_STATS`) has no PRA entry.
  - `record_gate.py:461` says so: "Keys without a projection record (bet record only): NBA
    moneyline / pra props".
  - `drop_reason` (`record_gate.py:145-160`) returns None for a key with no record unless
    `AUTO_PICK_REQUIRE_PROVEN_RECORD=true` (default false), and PRA is not in
    `DEFAULT_PROVE_IN_KEYS`.
  - `model_review_service.py:91-122` and `scripts/nba_props_audit.py:25` do not load PRA either.
  - Data (`daily_review_2026-11-17.txt` line 259): bets in 30d by model version are
    `{'sum-pra-v1': 4, 'xgb-202611141637': 2, ...}`; [prop] record 1-7, -6.00u.
  - Record gate: `WITHHELD NBA/player_prop/points ... shrunk ROI -3.5%`.
  - Fair-price secondary flags on `player_points_rebounds_assists` hit 51.2% of 123, ROI -5.6%.
- **Why it misses**:
  - The best-scoring prop candidates are the ones furthest from the line, and PRA adds three
    projections' errors together.
  - The points part is worse than the line (5.34 vs 4.97 MAE on lined rows), so PRA inherits the
    widest errors with no brake on them.
  - That makes PRA the most likely prop to clear the score threshold and the least likely to win.
- **Confidence**: CONFIRMED for the missing gate and measurement (code and the bet-version counts).
  The PRA record itself is HYPOTHESIS. To settle it, grade `pred_pra_projections` against
  `pred_recent_games` (points + rebounds + assists) with the stored `fanduel_line` and
  `fanduel_over_under`, from 2026-10-20 on.
- **Status**: new.
- **Fix**:
  - Add `"pra_ou": ("pra", "actual_pra", "projected_pra")` to `_NBA_PROP_STATS`
    (`nba_accuracy_service._PROPS` already has `pra_ou`).
  - Until that record exists, add `NBA/player_prop/pra` to `DEFAULT_PROVE_IN_KEYS`.
  - Add PRA to the model review loader.
  - Size S.

## F2. The retrain promotes without any check against the line, and the points line check is always empty

- **What is wrong**:
  - Prop models go live when their holdout MAE beats the live model's by any amount. The
    comparison with the stored betting line is "reported, not gating".
  - For points that comparison is always empty (n=0).
  - Users get a new model every week that is no closer to beating the book, sometimes switched on
    by a rounding-size difference.
- **Evidence**:
  - `backend/app/services/etl/nba/ml_training/run_train_props.py:181-185` ("Reported, not
    gating"); the upload decision is `:260-278`, on MAE only.
  - Points n=0: `holdout_line_comparison` calls `residual.dataset.load_lines`, which only builds
    lines for `STAT_COLUMN = {"rebounds", "assists"}` (`residual/dataset.py:18`, `:268-273`).
  - Holdouts in `retrain_43952830509.log` (11-16):

    | Stat | Lined holdout rows | Model MAE | Line MAE | Side hit rate | Edge slope t | Outcome |
    |---|---|---|---|---|---|---|
    | Rebounds | 1,339 | 2.034 | 1.959 | 50.2% | 1.64 | **uploaded** (`xgb-202611162103`) |
    | Assists | 1,073 | 1.731 | 1.678 | 52.3% | 2.67 | rejected_by_champion |
    | Points | 0 (log line 252480) | none | none | none | none | rejected_by_champion |

    - Rebounds was uploaded because 1.907597 beat the champion's 1.907761 (log lines 758406-758413).
    - Assists was rejected at 1.3748 vs 1.3739; points at 4.769 vs 4.762.
  - 11-14 run (`retrain_43614347262.log`): points, rebounds and assists all uploaded, beating the
    champion by 0.039 / 0.010 / 0.0007 MAE. Those are the live `xgb-202611141625` (points) and
    `xgb-202611141637` (assists).
  - The #182 PR body says "The models still do not beat the line (points 5.222 vs 4.884 on lined
    rows)".
  - Production agrees (`daily_review_2026-11-17.txt` lines 91, 117, 142). Projection vs line MAE
    on the same rows: points 5.34 vs 4.97, rebounds 2.03 vs 1.97, assists 1.76 vs 1.71.
- **Why it misses**:
  - A pick is a bet that the projection beats the line. Every model being shipped is measurably
    worse than the line on exactly the rows that get bet.
  - Promoting on overall MAE (all 4,280 holdout rows, two thirds of them unlined bench players)
    optimises the wrong population.
  - The champion is also scored partly in-sample: the 11-16 holdout overlaps the 11-14 champion's
    training rows by about two days.
- **Confidence**: CONFIRMED (code and logs).
- **Status**: listed and still open (NBA-4, bd YetAI-3tl).
- **Fix**:
  - In `run_train_props.run`, refuse upload unless `line_comparison.beats_line` and
    `slope_t >= 2`. Emit `rejected_by_line_gate`, which the workflow grep already knows.
  - Use the same `residual.gate` rule for the residual model.
  - Make `load_lines` work for points (add `"points"` to `STAT_COLUMN`, `PROJECTION_TABLE` and
    `PROJECTION_COLUMN`).
  - Require a minimum MAE gain (for example 0.5%) to replace the champion.
  - Size S.

## F3. The record gate keeps rebounds and assists open on the old model's record, valued at -110 instead of the real -125/-128

- **What is wrong**:
  - The gate's projection record is every stored call in 90 days. That is mostly the old,
    unversioned model, with sides written under the pre-#170 rule.
  - About 80% of those calls have no stored price and are valued at -110.
  - The side we call costs a median -125 (rebounds) and -128 (assists), which needs 55.6% and 56.1%
    to break even.
  - So rebounds and assists stay pickable on a record the current model did not make, at prices
    nobody gets. Two of the 8 prop bets carry the assists model version `xgb-202611141637`. The
    others are 4 PRA plus points and threes bets placed before those keys were withheld (gate
    lines: points 1 bet, threes 2).
- **Evidence**:
  - `record_gate.py:309-329`: no `model_version` filter; window `DEFAULT_WINDOW_DAYS = 90`;
    `ou_call_graded_record(..., price_field="fanduel_price")`.
  - `odds_math.units_for_result:78-83` values an unpriced row at `BREAKEVEN_PRICE` (-110).
  - Price column added on 11-13 (`alembic/versions/20261113_prop_fanduel_price.py`, PR #175). No
    backfill.
  - "priced" grows by exactly the new calls each day: points 167 → 276 → 376 (+109, +100) against
    calls +109, +100. Every new row is priced; every row before 11-13 is not.
  - `_fanduel_lines.py:377-380` also nulls the price when a rerun with no fresh line flips the
    side.
  - Data (`daily_review_2026-11-17.txt` lines 215-217):
    - rebounds priced 323 of 1,681, breakeven 55.6% at median -125;
    - assists priced 252 of 1,312, breakeven 56.1% at median -128;
    - version counts (lines 260, 275): assists `xgb-202611141637` 621 rows vs None 4,594.
  - Newest two days, at real prices (see the table below): assists -17.9u on 153 calls; rebounds
    -1.9u on 185.
- **Why it misses**:
  - A key is withheld only when shrunk ROI < -2%. Valuing old 54-57% edge>=1 calls at -110 shows
    them as roughly +5% to +8% ROI. At -125/-128 they are roughly breakeven or negative.
  - The gate also drops (rather than grades) pre-#170 rows whose stored side contradicts the
    projection (`_prop_qualifies`, `record_gate.py:300-312`). That throws away a block of old under
    calls and biases the record toward overs.
- **Confidence**: CONFIRMED for the mechanism (code and the priced counts). The exact gate ROI for
  rebounds and assists is not printed for keys that are not withheld (HYPOTHESIS). To settle it:
  `PYTHONPATH=. python3 -c "from app.core.database import SessionLocal; from app.services.auto_pick import record_gate as g; from datetime import datetime; print({k:v for k,v in g.load_records(SessionLocal(), datetime.utcnow()).items() if k[0]=='NBA'})"`
- **Status**: new. NBA-8 is the same problem for totals and spread, fixed there by version scoping;
  props were not scoped.
- **Fix**:
  - Scope the NBA prop record to the live `model_version` (as `totals_projector.version_pick_record`
    does) or to `date >= 2026-11-15`.
  - Value unpriced rows at the stat's median stored price, not -110. Until then, put rebounds and
    assists through prove-in.
  - Size S.

## F4. The two review scripts disagree because one grades the stored side and the other the projection side; the daily email also compares MAEs on different rows

- **What is wrong**:
  - "Projection accuracy" in the model review grades the stored `fanduel_over_under`.
    `nba_props_audit.py` grades sign(projection − line).
  - Before #170 (11-10) the stored side used the old rule ("under only when more than 1.5 below
    the line"), and register NBA-11 said those records "must be recomputed". They never were.
  - Separately, the daily email's "MAE x, line MAE y" compares projection error on every row
    (mostly unlined bench players) with line error on lined rows only. The owner sees the
    projection beating the line when it loses.
- **Evidence**:
  - `model_review_service.py:135` (pick = `fanduel_over_under`) and `:391-405`.
  - `nba_props_audit.py:39-50` (`(proj > line) == (actual > line)`).
  - No code recomputes stored sides: `grep pick_side` finds only `_fanduel_lines.py`.
  - Same rows: the model review's 1,681 rebounds calls equal the audit's "1681 lined rows" this
    season.
  - The audit's 1,707 picks include 34 last-season rows, so at least 857 hits this season (51.2%)
    against the stored side's 825 (49.1%). At least 32 rows were graded on a side the projection
    did not take.
  - Since the fix the two agree exactly on the new rows:

    | Stat | Day | Audit delta | Review delta |
    |---|---|---|---|
    | Rebounds | 11-16 | +98 picks, about +56 hits | 55/98 |
    | Rebounds | 11-17 | +87, about +44 | 44/87 |
    | Assists | 11-16 | +81, about +39 | 39/81 |
    | Assists | 11-17 | +72, about +34 | 35/72 |
    | Points | 11-16 | +108, about +53 | 54/109 |
    | Points | 11-17 | +100, about +52 | 51/100 |

  - MAE: `model_review_service.py:417-423` computes `errs` over all scored rows and `line_errs`
    over lined rows only.
    - Daily email: points "MAE 4.85, line MAE 5.03", assists "1.39 vs 1.71", threes "1.00 vs 1.22".
    - Same rows (audit): points 5.34 vs 4.97, assists 1.76 vs 1.71.
- **Which feeds the record gate**: neither exactly.
  - The gate (F3) uses the stored side, but only rows where the called side clears the line by the
    fill-floor edge. Pre-#170 rows with a contradicting side are dropped, not graded.
  - The model review's 49.1% is the honest "as published" record of what users saw.
  - The audit's 52.2% is "what the projection implied", which was never published for the
    pre-11-10 rows.
  - For anything forward-looking, both should use rows from 11-15 on only.
- **Confidence**: CONFIRMED (code, and the day-over-day reconciliation above).
- **Status**:
  - NBA-11 was "Fixed on main", but its follow-up (recompute old records) was not done.
  - The MAE comparison problem is new.
- **Fix**:
  - In `stats()`, compute `mae` and `line_mae` on the same lined rows, and print all-row MAE
    separately.
  - Add `--since 2026-11-15` (and a model_version split) to both scripts.
  - Optionally rewrite stored sides for rows before 11-11 with `pick_side`, keeping the published
    side in a new column.
  - Size S.

## F5. NBA Weekly Retrain goes red on normal gate outcomes; nothing is skipped, but real failures are now invisible

- **What is wrong**:
  - The workflow means "gate outcome = warning, exit 0", but GitHub runs the step with `bash -e`.
  - `python ... | tee train.log` under `set -o pipefail` exits the step as soon as the trainer
    returns 1, before the `grep ... rejected_by_champion` line runs.
  - The owner sees a red run on 11-14 and 11-16 whether or not anything broke.
- **Evidence**:
  - `.github/workflows/nba-weekly-retrain.yml` step script (`set -uo pipefail` does not undo
    `-e`); the log shows `shell: /usr/bin/bash -e {0}`.
  - `ml_training/__main__.py:58-61` returns 1 for any status other than ok;
    `train_spread_model.py:175-176` raises `SystemExit(1)`.
  - `retrain_43952830509.failed.log:253240`: `##[error]Process completed with exit code 1.`
    comes right after the JSON with `"status": "rejected_by_champion"`. No `::warning::` line was
    ever printed.
  - Same for spread `below_baseline` (`retrain_43614347262.failed.log:772`).
  - The residual CLI returns 0 on `gate_failed` (`residual/__main__.py:33-35`), so
    residual_rebounds stayed green while failing its gate.
- **What each run did**:

  | Run | Stat | Outcome | Holdout MAE | Live model (champion) |
  |---|---|---|---|---|
  | 11-14 | spread | below_baseline vs market (11.77 vs 11.21) | | |
  | 11-14 | rebounds | uploaded | 1.9106 | 1.9202 |
  | 11-14 | points | uploaded | 4.7709 | 4.8102 |
  | 11-14 | assists | uploaded | 1.3851 | 1.4008 |
  | 11-16 | points | rejected_by_champion | 4.769 | 4.762 |
  | 11-16 | spread | below_baseline (11.71 vs 11.18) | | |
  | 11-16 | assists | rejected_by_champion | 1.3748 | 1.3739 |
  | 11-16 | residual_assists | first_upload | 1.641 (line 1.662) | |
  | 11-16 | rebounds | uploaded | 1.90760 | 1.90776 |
  | 11-16 | residual_rebounds | gate_failed (worse than line, edge not predictive) | | |

  - 11-14 had no residual jobs: it ran at 16:12 UTC, before #184 merged at 23:28 UTC.
  - `fail-fast: false`, so a red job never skipped another stat. Threes, steals, blocks and free
    throws are not in the matrix by design (served as last-10 averages).
- **Training data cleanliness**:
  - The 11-14 holdout MAEs (4.771 / 1.911 / 1.385) match the #182 PR's "retrain on repaired data"
    figures (4.774 / 1.907 / 1.383).
  - Row counts grew plausibly: 21,125 to 21,397 for two more game days.
  - That points to training after the re-date and dedupe. I could not confirm it from a log of the
    repair itself (no workflow run; it was a manual script).
  - Gaps that remain are in F7.
- **Confidence**: CONFIRMED.
- **Status**: new. #177 claimed a "working retrain loop".
- **Fix**:
  - In the step, run `python3 ... > train.log 2>&1 || true; cat train.log` (or `set +e`
    around it) before the grep.
  - Or have the CLIs exit 0 for gate outcomes and non-zero only on errors, and make the residual
    CLI consistent with them.
  - Size S.

## F6. "Residual shadow: no shadow rows" happens because no residual model existed until 11-16 16:11 ET, and the rebounds one never will under its gate

- **What is wrong**:
  - The shadow writer (`residual/shadow.py:166-170`) returns `no_model` and writes nothing until
    `s3://yetibets/nba/ml_models/residual_<stat>.pkl` exists.
  - The only trainer is the weekly retrain matrix. Its first run with residual jobs was 11-16
    20:44 UTC:
    - residual_assists uploaded at about 21:11 UTC (`retrain_43952830509.log` lines 505722-505760,
      version mislabelled `xgb-202611162111` for a ridge model);
    - residual_rebounds failed its line gate (worse than line, slope t 0.92;
      log lines 758663-758682).
  - The review counts only rows dated before today (`model_review_service.py:982-991`), so 11-17
    rows cannot show until the 11-18 report.
  - The only run that could have written 11-16 rows was the 17:00 ET pregame refresh.
- **Why it matters**: three days of "shadow" collected nothing. Rebounds will collect nothing until
  a weekly run passes the gate (next chance Monday 11-23), so the planned evaluation clock has not
  started.
- **Confidence**: CONFIRMED that no model existed before 11-16 (logs). HYPOTHESIS for 11-16/11-17
  rows. To settle it:
  `SELECT date, stat, count(*), min(created_at) FROM pred_nba_prop_shadow GROUP BY 1,2 ORDER BY 1;`
  plus the celery result of `app.tasks.etl_pipeline.nba.residual_shadow` for the 11-16 17:00 ET
  run.
- **Status**: new. bd YetAI-g92 is open.
- **Fix**:
  - Expected: assists rows from 11-17 should appear tomorrow. If they do not, read the task result.
  - For a shadow study, write rows from an ungated (but never published) model, so the shadow
    measures the model rather than waiting for it to pass.
  - Size S.

## F7. No rotation, injury or teammate signal, and no projection change after the last refresh

- **What is wrong**:
  - The XGB features (`_feature_engineering.py:201-374`) are the player's own past box scores,
    opponent defense, the game line, rest and month. No teammate-availability, starter or lineup
    feature exists.
  - `update_expected_minutes` builds `pred_player_expected_minutes`, but no NBA projector reads it
    (only WNBA does).
  - Injury handling only skips the injured player himself (`out/ir/doubtful`,
    `generate_rebounds_predictions.py:37-49`). Questionable players are projected as if healthy.
  - The pregame refresh (12:00 and 17:00 ET, `celery_app.py:118-122`; phases
    `etl_pipeline.py:546-559`) re-runs the projectors, but the only inputs that change intraday are
    the game spread and total. It mostly re-fetches lines and re-derives the side. Teammates of a
    scratched star are never re-projected.
  - Nothing runs between 17:00 ET and tip, where most late scratches land.
  - The 11:00 ET auto-pick run (`celery_app.py:354-360`) uses the 03:30 run's projections and lines
    (`player_prop_source.py`, stored `fanduel_line` and `fanduel_price`), an hour before the first
    refresh.
- **Evidence**:
  - `daily_review_2026-11-17.txt` lines 103-112 (points by team, this season):
    - over-projected: Bucks bias -1.62 with 58% overs; Mavericks -1.30 with 83% overs; Rockets
      -1.19 with 67% overs; Wizards -1.13 with 75% overs;
    - under-projected: Thunder +0.55 with 36% overs; Magic +0.37 with 37% overs.
  - Rebounds and assists show the same teams (lines 128-130, 153-157). Team-wide leans are what a
    missing rotation signal produces: a returning or departed player shifts every teammate's minutes.
  - Misses: Terrence Shannon Jr. projected 10.4 points, scored 34; Kasparas Jakucionis projected
    4.8, scored 25. Both look like role-change games.
  - The non-rotation misses (Isaiah Crawford 1.43 rebounds → 10, Myron Gardner 0.12 threes → 4,
    Mo Bamba 0.0 → 6) have no line, so they are never picked.
    - `today_active_players.py` projects the whole roster for anyone with 5 or more games.
    - The board caps rows at 200 per stat by minutes per game (`predictions.py:82`), so on small
      slates deep-bench rows are shown.
    - They inflate the "graded player-games" counts: points 4,273 rows, only 2,056 lined.
- **Why it misses**: the line moves on injury news and the projection does not. The edge the model
  shows is then mostly the market's information the model lacks: the side we call carries a median
  -125 to -140 juice and negative probability CLV (F8).
- **Confidence**:
  - CONFIRMED that the signal is absent (code).
  - The size of the team effect is HYPOTHESIS. To settle it: for this season, regress
    (actual − projection) on (teammates in the top-5 by minutes ruled out that day, from
    `pred_player_injury_status` history or the box scores) per lined row.
- **Status**: new (not in the register).
- **Fix** (by expected gain per effort):
  1. Move the 11:00 auto-pick run after the 12:00 refresh, or re-fetch the line at pick time.
  2. Add a 18:00-18:30 ET refresh restricted to games tipping after 19:00.
  3. Add two features: minutes vacated by teammates ruled out (from expected minutes) and the
     player's minutes share when the same teammates sat before.

  Sizes: S, S, M.

## F8. Points/threes/steals CLV is measured against the same fetch that set our line; low CLV coverage is just the 30-day denominator

- **What is wrong**:
  - For points, threes and steals the only snapshots are the projection ETL's own fetches. The last
    one before tip is the 17:00 ET refresh, the same response that wrote the stored line, so line
    CLV is 0 by construction.
  - Rebounds and assists get a real close from `close_capture` about 20 minutes before tip.
- **Evidence**:
  - `close_capture.py:56-58`: default markets are `player_rebounds,player_assists` only.
  - Beat every 10 minutes, lead 25 minutes (`celery_app.py:126-130`).
  - The daily review shows "line CLV mean +0.00 / median +0.00", close 142 / 138 / 154 minutes
    before start for points / threes / steals, against 20 minutes for rebounds and assists
    (`daily_review_2026-11-17.txt` lines 290-294).
  - Coverage: points 209 calls with a close, exactly the 209 calls graded since 11-15; snapshots
    only exist from #184 (11-14). The low percentage is the 30-day denominator, not a join bug.
  - Real CLV on rebounds/assists: probability CLV -2.5 / -1.7 points, only 16-19% positive. That is
    no edge.
- **Confidence**: CONFIRMED.
- **Status**: new.
- **Fix**:
  - Add `player_points,player_threes` to `NBA_CLOSE_CAPTURE_MARKETS`. That is about 2 more
    credits per event.
  - Have the review mark CLV as "no independent close" when the close snapshot equals the
    projection's fetch.
  - Size S.

## F9. Training and serving still differ on the game-line features, and short current-season samples drop players

- **What is wrong**:
  - The `spread`, `total`, `is_home`, `is_favorite` and `blowout_risk` features come from
    `pred_nba_game_lines` (`_feature_engineering.py:176-198`, `:341-355`). Training rows with no
    stored game line get all of them as 0, including `is_home=0` even when the box row says
    `home_game=True`.
  - At serving time today's game line always exists.
  - Separately, `player_games` returns only current-season games once a player has 1
    (`_samples.py:19`), and `build_features` returns None under 5 games (`:228-230`). A player in
    games 1-4 of the season, or back from a long absence, gets no projection at all.
- **Evidence**:
  - The code paths above.
  - Last season only 664 of 1,322 games have a stored market total
    (`daily_review_2026-11-17.txt` lines 5, 17). That suggests about half of the 2025-26 training
    rows train with game-line features of 0.
  - The #182 PR reports 25,022 box rows after the repair, while a full 2025-26 regular season plus
    playoffs plus this season should be roughly 30k+. That hints at missing box scores (gaps
    distort last-N, rest and opponent-defense features).
- **Why it misses**:
  - The depth-2 model learns `total == 0` as an early-season time marker, and the blowout/minutes
    effect from only half the data.
  - At serving time every row is in the "has a line" branch. Size unknown, likely small next to F2
    and F7.
- **Confidence**: CODE-ONLY / HYPOTHESIS. To settle it:
  - `SELECT date_trunc('month', game_date) m, count(*) FROM pred_nba_game_lines WHERE game_date >= '2025-10-01' GROUP BY 1 ORDER BY 1;`
  - `SELECT date_trunc('month', game_date) m, count(DISTINCT (game_date, opponent_team_id)) team_games, count(*) rows FROM pred_recent_games WHERE game_date >= '2025-10-01' GROUP BY 1 ORDER BY 1;`
    (expect about 2 × games that month).
- **Status**: new. The register's NBA-3 covers rest in totals, not props.
- **Fix**:
  - Take `is_home` from the box `home_game` (training) and the schedule (serving).
  - Drop spread/total or fill them from `pred_nba_spread_actuals` and the historical odds backfill.
  - Let `player_games` fall back to last season when the current sample is under 5.
  - Size S.

## Not a finding (checked)

- **Duplicates and dates**:
  - `update_recent_games.py:138-150` plus the `api_game_id` unique key (migration
    `20261114_recent_games_api_game_id.py`) converge to one row per player per game on the Eastern
    date.
  - Rest and back-to-back are computed from the player's own box rows (`_feature_engineering.py:287-298`).
  - Opponent defense is computed as of the game date from box rows (`_team_defense.py`).
  - Training and serving use the same `build_features`.
- **Leakage**: features use only `game_date < D`. The line is fetched in the same call as the
  projection, before tip (rows freeze at start: `_stale_rows.active_players_not_started`). I found
  no post-game information in either.
- **Stale lines**:
  - Since #153 (10-26) a rerun that finds no FanDuel line keeps the old one and re-derives the side
    (`_fanduel_lines.py:373-381`). That can pair a morning line with an afternoon projection, but
    only for players FanDuel pulled.
  - It cannot be checked for the old edge >= 2 rows, because snapshots begin 11-14 (the
    historical odds backfill, `scripts/odds_history_backfill.py`, could). It is not needed to
    explain the bucket (see the table below).

## Newest days only (day-over-day differences of the cumulative counts)

The 11-14 to 11-15 difference is the box-score regrade (lined rows jumped 879 → 1,530 for
rebounds), not a game day. These use 11-15 → 11-17, which is the games of 11-15 and 11-16. All
calls are priced, on post-retrain models, post-repair, with stored side equal to projection side.

| Stat | Calls (2 days) | Hit | 95% ± | Units (real price) | ROI | Projection vs line MAE, same rows |
|---|---|---|---|---|---|---|
| Points | 209 | 105 (50.2%) | ±6.8pt | -13.3u | -6.4% | 5.34 vs 5.06 (±0.1) |
| Rebounds | 185 | 99 (53.5%) | ±7.2pt | -1.9u | -1.0% | 2.20 vs 2.14 (±0.09) |
| Assists | 153 | 74 (48.4%) | ±7.9pt | -17.9u | -11.7% | 1.68 vs 1.63 (±0.09) |
| Threes (last-10 average) | 153 | 81 (52.9%) | ±7.9pt | -12.0u | -7.8% | n/a |
| Steals (last-10 average) | 17 | 11 | n/a | n/a | n/a | n/a |

Edge buckets on the new days:
- Rebounds at edge >= 1: about 15 of 32 (47%). At edge >= 2, only 2 new rows in two days (71 of
  the 73 rows existed by 11-15, and 50 existed by 11-14 under the old model).
- Assists at edge >= 1: about 14 of 21.

Verdict: too small to tell on hit rate, but nothing is better. Every stat is still worse than the
line on MAE and negative in units at the prices actually offered. It agrees with the 11-16
holdouts (side hit 50.2% rebounds, 52.3% assists) and with negative probability CLV.

## Per-stat verdict

| Stat | Verdict | What would make it genuinely better |
|---|---|---|
| Points | Plumbing fine (box scores fixed; serving okay). The line check is broken (n=0). No edge: lined MAE 5.34 vs 4.97, withheld by the gate. | Keep withheld. Fix the points line join and add the line gate (F2). Add the rotation features (F7). Publish line + k·(model − line) with a fitted small k instead of raw XGB. |
| Rebounds | Plumbing fine. No edge: holdout side hit 50.2%, MAE worse than line. The edge >= 2 bucket is old-model, small-n, not evidence. Picks are allowed on an old, -110-valued record (F3). | Scope the gate by version and real price (F3). Refresh before tip (F7). Residual model failed its gate: needs the teammate-out signal more than a new learner. |
| Assists | Plumbing fine. No edge: holdout MAE 1.731 vs line 1.678, side hit 52.3% vs breakeven 56.1% at -128. Worst new-days ROI (-11.7%). | Same as rebounds. Residual assists passed its line gate narrowly (1.641 vs 1.662, t = 2.06): let the shadow run 300+ rows before trusting it. |
| Threes | Plumbing fine (last-10 average by design). No edge: 49.3% stored, breakeven 58.3% at -140. Withheld. | Keep withheld. Use a real close (F8) to see whether any sub-segment beats the close before modelling. |
| PRA | Plumbing gap: ungated and unmeasured (F1). Inherits the points error. | Gate it now (F1). Then the same as points. |
| Steals | Too new (lines since about 11-15; 21 calls). Prove-in key. | Wait for 30+ graded calls. Add steals to close capture. |
| Blocks / free throws | Unknown: no line column for blocks (`player_prop_source.py:32`), no free-throw market. Not pickable. | Nothing until lines are stored. |

## What to do, ranked by expected gain per effort

1. **Gate PRA** (F1, S). It removes half of the losing prop bets immediately.
2. **Version-scope the prop record gate and value it at real prices** (F3, S). Rebounds and assists
   would most likely be withheld or prove-in, which ends the auto picks until a model earns them.
3. **Line gate in the retrain and a points line join** (F2, S). Stops promoting models that lose to
   the book.
4. **Move the 11:00 pick after the 12:00 refresh and add a late refresh** (F7, S). Cuts stale-line
   and late-scratch losses.
5. **Fix the review's MAE comparison and add a since-11-15 view** (F4, S). Stops the daily email
   telling the owner the projections beat the line.
6. **Make the retrain go red only on real errors** (F5, S).
7. **Close capture for points/threes** (F8, S). Without it there is no honest CLV for half of the
   markets.
8. **Teammate-out / minutes features** (F7, M). The only change on this list with a plausible path
   to an actual edge. The others stop losses and fix the measurements.
9. **Game-line feature skew and short-sample fallback** (F9, S). Small, but cheap.
