# Review 2026-11-17: NHL projections, plus the measurement and scheduling infrastructure

Scope: `etl/nhl/`, `nhl_accuracy_service.py`, odds snapshots, CLV (`prop_clv.py`, `odds_math.py`),
fair-price shadow (`services/fair_price/`, `tasks/fair_price.py`), the daily model review,
Odds API credit accounting, Celery beat, queues and worker roles. Code is origin/main 5b662edf.
All production numbers come from `.factory/review-1117/evidence/daily_review_2026-11-{14..17}.txt`
(cited as R14..R17) and `gh run list`.

Short version: the NHL rebuild (#183) did what the register asked, and the result is a model with
no edge against the line. The worse problems are in the yardsticks. Three of the numbers the
owner is reading to decide direction are wrong by construction: the fair-price shadow interval,
the NBA prop "prob CLV", and the projection-accuracy lines that mix old and new models.

---

## 1. The fair-price shadow interval is far too narrow, and the decision rule will close after about 4 game nights

**What is wrong.** The review prints primary CLV "-1.1pt [-1.2, -1.0]" (R17:307). That interval
is clustered by game date, and the 85 graded flags come from 2 game dates (8 flags on 11-15 and
77 on 11-16). With 2 clusters the "cluster-robust" standard error only measures how far apart the
two daily means are. It says nothing about the spread between flags. The owner sees a precise
negative number that is not precise.

**Evidence.**
- `backend/app/services/fair_price/backtest.py:179-192` `clustered_mean`: se = sqrt(G/(G-1) ·
  Σ_g (Σ_i (x_i − m))²)/n, with z = 1.96 whatever G is. When G < 2 it returns no interval. That
  is why the "9h+" bucket shows "CLV -0.7pt (n=46)" with no interval: every flag in it is from
  one date (the flagger first ran after the 11-15 12:59 UTC deploy, so there was no 03:30 snapshot
  on 11-15).
- Reproduced exactly: 8 flags at −0.8 (R16:121) plus 77 at −1.131 (the 11-17 total minus the
  11-16 total) gives `clustered_mean` = −1.10, se 0.056, CI [−1.21, −0.99]. That is the printed
  interval to the digit.
- Simulation (true CLV 0, per-flag SD 5pt as in the backtest, day effect SD 1pt, 8 + 77 flags):
  the printed "95%" interval covers the truth **39%** of the time. Its median width is 1.0pt,
  while an honest interval at n=85 is about ±1.1pt or more.
- The decision is pre-registered at the first 300 primary flags (`docs/fair-price-shadow-decision.md`).
  11-16 alone produced 89 primary flags (R17:304), so 300 arrives in about 3 more slates, on about
  4 or 5 game dates. The power table in that doc was computed from the backtest's **153** date
  clusters. Simulated at 300 flags with no true edge: with 4 dates, NO GO fires 7.8% of the time
  (nominal 2.5%) and the coverage is 85%; with 5 dates, 4.6%; with 30 dates, 2.9%.
- Flags are also not independent bets. One flag is allowed per (event, market, player, side,
  book) (`shadow.py:106-131`), so one player-side priced at three books counts as three flags.
  They share one box-score outcome and nearly the same CLV. The Wilson hit-rate interval
  (`report.py`, `backtest.wilson`) ignores this.

**Why the live CLV is negative.** It is **not** the mechanical vig offset. The live CLV uses the
same definition as the backtest: no-vig close minus the implied probability of the flagged
price, with the vig on the flagged price (`grade.py:88`, `docs/fair-price-shadow-decision.md`
"Metrics"). The flag rule also builds in a margin: EV ≥ 5% at a leave-one-out fair p
(`flags.py:148-157`) means p − 1/dec ≥ 0.05/dec, about +2.4 to +2.6pt at the time of the flag.
So −1.1pt at the close means the consensus moved about 3.5pt **against** the flagged side between
flag and close.
- Stale snapshots are not the cause. "NBA latest 17:18" is 17:18 UTC, which is the 12:00 ET
  pregame refresh. The review ran at 21:50 UTC (16:50 ET; `gh run list` "Daily Model Review"),
  before the 17:00 ET refresh. The overall latest, 21:45 UTC, is the 16:45 ET NHL refresh. Both
  are what the schedule produces.
- A different close definition is not a big factor either. The backtest close was 5-10 min before
  tip (`docs/edge-engine-backtest-2025-26.md:24-25`). The live close is the close-capture call 15-25 min
  before tip (`close_capture.py`), and the grader refuses any close more than 60 min out
  (`grade.py:28,76-79`). One timing difference is real: live flags come from the 03:30 ET fetch
  (about 15 h before tip, the "9h+" bucket) and the 12:00 ET fetch ("6-9h"). The backtest flagged
  at T-600 and T-360 only.
- One untested mechanism fits the sign. Freshness is judged by our fetch time (`flags.py:77-82`),
  not by the book's own `last_update`. If the flagged book had already moved on news and the
  books in the pool had not, the flag is adverse selection, and the close then moves against it.
  Each flag stores `book_updated_at`, and the pool books' timestamps are in `odds_line_snapshots`,
  so this can be checked (SQL below).

**Mechanism and size.** If this number goes to the owner as "CLV is reliably negative", it reads as
NO GO. In truth the sample is n=85 on 2 nights, and the honest reading is about −1.1 ± 1.1pt or
wider. It is consistent with anything from a small edge to a clearly negative one. The 6-9h bucket
(−2.0, n=35, all one date with 15/35 hits) is a single slate.

**Confidence.** CONFIRMED for the interval: the printed CI is reproduced exactly from the
day-level means, and the coverage was simulated with the repo's own function. HYPOTHESIS for why
CLV is negative. To settle it:
```sql
-- how many independent bets, and does CLV depend on which book updated first?
SELECT f.game_date, count(*) flags,
       count(DISTINCT (f.event_id, f.player_key, f.side)) player_sides,
       avg(f.clv) clv
FROM fair_price_shadow_flags f
WHERE f.rule_version='fp-shadow-v1' AND f.tier='primary' AND NOT f.is_close
  AND f.result IN ('hit','miss','push') GROUP BY 1 ORDER BY 1;
-- flagged book's last_update vs the median last_update of the other books at the flag time
SELECT width_bucket(EXTRACT(epoch FROM (f.book_updated_at - o.med))/60, -120, 120, 6) b,
       count(*), avg(f.clv)
FROM fair_price_shadow_flags f
JOIN LATERAL (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY s.book_updated_at) med
              FROM odds_line_snapshots s
              WHERE s.event_id=f.event_id AND s.market=f.market AND s.player_key=f.player_key
                AND s.book<>f.book AND s.first_seen_at<=f.observed_at AND s.last_seen_at>=f.observed_at) o ON true
WHERE f.tier='primary' AND f.clv IS NOT NULL GROUP BY 1 ORDER BY 1;
```

**Status.** New. The decision rule itself is the bug: it was written with the backtest's cluster
count in mind.

**Fix (S, before the 300th flag, about 2026-11-20).** Publish a rule version `fp-shadow-v2`.
Recomputing the flags so far under it costs nothing, because the rule only changes how they are
scored. Changes:
(a) decide at ≥300 flags **and** ≥30 distinct game dates;
(b) use a t critical value with G−1 degrees of freedom in `clustered_mean`;
(c) score one flag per (event, player, side), at its best price, and report n_dates next to every
    interval (`report.py:_row_line`);
(d) add a "source fetch" column (03:30 / 12:00 / 17:00 / close capture).
Until then, print "interval unreliable (G=<n> dates)" whenever G < 20.

---

## 2. The NBA prop "prob CLV" in the review has a built-in negative offset, and for points, threes and steals it is a tautology

**What is wrong.** The review's CLV for NBA props (R17:290-294: −1.7 to −2.5pt, 8-19% > 0, line
CLV about 0) does not measure whether the projection's side beat the market:
1. `odds_math.prob_clv` (`backend/app/services/odds_math.py:194-207`) is the **no-vig** closing
   consensus probability minus the **with-vig** implied probability of the price taken. A pick
   with no skill on an unmoved market scores −2.4pt at −110/−110 and −3.5pt at −128/−102
   (reproduced locally). Even with line shopping (best of 3 books at −105 against a 50/50
   consensus) it scores −1.2pt. Zero is not the no-skill level. That level is minus half the
   hold, net of line shopping.
2. The price taken is `best_*`: the best-EV quote across the 10 PROP_BOOKS. It is overwritten on
   every projector run (`_fanduel_lines.py:383-398`), so for a 19:00 game it comes from the
   17:00 ET refresh. For points, threes, steals, blocks and PRA, the last snapshot before tip is
   that **same 17:00 fetch**, because close capture only fetches rebounds and assists
   (`close_capture.py:55-57`, default `player_rebounds,player_assists`). The "close" is therefore
   the quote the pick was priced from. Line CLV is 0 by construction: points +0.00/+0.00,
   threes +0.00/−0.00, steals +0.00/−0.00 (R17:291-294). Prob CLV is then just the EV of the best
   quote at 17:00, which contains no information about the pick.
3. "Close N min before start" is `commence_time − last_seen_at` of that row
   (`model_review_service.py:858-860`). 142, 138 and 154 min is 17:00 ET to a 19:00-19:30 tip.
   The 20 min for rebounds and assists is the close capture. A close 142 min before tip is not a
   close. The fair-price grader already rejects anything more than 60 min out (`grade.py:28`);
   the review does not apply the same rule.

**Corrected reading.**
- Points, threes and steals: true CLV is undefined (0 by construction). The −1.7, −2.0 and −2.5pt
  show that the picks sit, on average, at prices 1.7 to 2.5pt worse than the no-vig consensus even
  after line shopping. That is the hold, not a model verdict.
- Rebounds and assists have a real close. Line CLV is +0.06 and +0.09 (the market moved slightly
  toward the picks). Prob CLV is −2.5 and −1.7. Subtracting an offset of the same size as points
  (−1.7 to −2.5) leaves roughly −0.8 to +0.8pt: **no measurable CLV either way**. This is
  consistent with the hit rates at the line (49-50%). The model has no edge against the line,
  and the yardstick is not hiding a positive one.

**Why only 10-19% have a close.** Snapshots started with #184, deployed 2026-11-14 23:28 UTC.
The 30-day window holds about 27 days of calls from before snapshots existed. This will heal
by mid-December and is not a bug.

**Confidence.** CONFIRMED. The code path was read end to end, and line CLV of exactly 0 together
with 138-176 min closes on exactly the markets close capture skips is the data signature of the
tautology. The offset was reproduced with `odds_math.prob_clv`.

**Status.** New. X-4 (closing lines) is "claimed fixed" by #184. Snapshots exist, but the close
is only real for rebounds and assists.

**Fix (S).**
(a) Report CLV as no-vig against no-vig: `consensus fair at close − consensus fair at the time
    the price was taken`, using `odds_snapshots.quotes_at(projected_at)`. Keep the current figure
    separately, labelled "EV at taken price".
(b) Drop any close more than 60 min before start (same rule as `grade.py`) and print the count.
(c) Set `NBA_CLOSE_CAPTURE_MARKETS` to all 7 prop markets. That costs about +5 credits per
    event, around +40 a day.
Files: `model_review_service.py:_clv_for_key`, `prop_clv.py`, the env setting.

---

## 3. The daily review cannot judge the new models and hides markets that are broken

**What is wrong.** "Projection accuracy (last 30d vs prior 30d)" blends rows from before and after
the 11-10, 11-14 and 11-16 fixes and model swaps, and several live markets never appear.
1. **No model_version scoping** except NBA totals and spread (`model_review_service.py:147-191`,
   `_version_key`). NBA props: points rows in 30d are `xgb-202611141625` 621 vs `None` 4,594
   (R17:273), so "931/1944 47.9%" is mostly the old model. NHL totals mix `heuristic-v1` 179 and
   `heuristic-v2` 71 (R17:271). The record gate already splits NHL by version
   (`record_gate.py:357-393`, v1 excluded), but the review only prints *withheld* keys
   (`model_review_service.py:589-606`). The v2 NHL keys are "unproven", so the v2 record is
   computed and never shown. On 11-14 the review listed NHL shots/total as WITHHELD (R14:44-45);
   from 11-15 NHL is absent from the gate section (R15, R16, R17).
2. **NHL shots has no loader.** `_nhl` (`model_review_service.py:229-281`) loads saves and totals
   only. There are 2,898 shot rows in 30 days (R17:270) and no accuracy line. The CLV section says
   so (`:818`). `nhl_accuracy_service._nhl_rows` already returns `player_shots`.
3. **NHL saves CLV can never join.** The goalie label is the stored `goalie_name`, which is the
   NHL boxscore short name ("C. Hellebuyck", R15:61; `confirm_starters.py:258`
   `goalie_name=db_row.name`). Snapshot `player_key` is the Odds API full name.
   `player_key("C. Hellebuyck")` = `c hellebuyck` and `player_key("Connor Hellebuyck")` =
   `connor hellebuyck` (run locally). Hence "13 calls, 0 with a close" on every day, even though
   the 16:45 refresh stores DraftKings saves snapshots.
4. The review's NHL loader does not use the accuracy service's preseason filter
   (`nhl_accuracy_service.py:51-52`). The *prior* 30-day window (09-18..10-17) holds preseason
   rows, so NHL "hit trend +6.8pt" (R17:229) compares against preseason.
5. **Markets with rows but no accuracy line**: NFL anytime TD (902 rows), NBA PRA (2,550), blocks
   (5,260), free throws (5,260), NHL shots. There is also no per-slate row-count check (register
   X-10), so a pipeline that writes nothing for a market is invisible. "Residual shadow: no shadow
   rows" has shown on all three days since #184 with no reason given. The task returns
   `no_model` silently (`etl/nba/residual/shadow.py:160-163`).

**Why it matters.** The owner cannot tell whether the 11-14 models are better, because their
rows are about 10-25% of each line. Broken markets (no shots grading, no saves CLV) look like
"no data yet".

**Confidence.** CONFIRMED (code, plus the versions table in R17 and the name format in R15).

**Status.** X-10 listed and still open. Items 1-4 are new.

**Fix (S).**
- In `_projection_section`, key every loader by `model_version` (as `_nba_totals` does), and add
  a "current version only" line per market.
- Add `player_shots` to `_nhl` via `nhl_accuracy_service._nhl_rows`, which also brings the
  preseason filter.
- Print `record_gate.gate_report` for unproven prove-in keys.
- Join NHL saves on `features_used.full_name` (the ESPN or roster full name that
  `starter_features_metadata` stores) or on `player_key` of the line-match name.
- Add a "rows per market for yesterday's slate vs games scheduled" table.

---

## 4. NHL: #183 fixed the inputs the register named; the rebuilt model has no edge against the line

**Register items checked in code (all fixed and verified in code):**
| Item | Where |
|---|---|
| NHL-1 current-season team stats (game type 2, any finished state) | `collect_historical_data.py:474-500` `_team_games`, `:548` |
| NHL-1 20-game cap removed | `collect_historical_data.py:96-131` (`max_games_per_team=None`) |
| NHL-1 all skaters | `nhl_api_client.py:38-42` (`limit=-1`, `gameTypeId=2`) |
| NHL-1 goalie per-season stats, last_game_date | `collect_historical_data.py:333-335,390,453` |
| NHL-5 team lookup by id | `team_totals_model.py`, `goalie_saves_model.py`, `_config.team_stat_or_default` (`filter_by(team_id=…)`) |
| NHL-6 roster-based skater selection | `daily_predictions.py:402-423` (current roster, ≥5 GP, top 6 + lined) |
| NHL-7 preseason | `daily_predictions.py:76`, `nhl_accuracy_service.py:51-52` |
| NHL-2 formula | `player_shots_model.py`: the shrunk shots/game rate only |

**What the v2 days show (day-over-day).**
- Saves (all rows are `heuristic-v2`; the first v2 slate was 11-14, after the 19:07 UTC deploy):
  4/10 calls, MAE 4.62 vs line 4.20 (n=24, R15:42); 6/13, 4.77 vs 4.44 (n=34, R16:42);
  6/13, 4.50 vs 4.19 (n=38, R17:228). The 11-16 slate added 4 graded goalies and 0 calls.
  Projection MAE is worse than the line by 0.3 saves on every day.
- Totals: 58/122 (n=207) → 58/122 (n=210) → 55/116 (n=198). MAE 1.89-1.90 vs line 1.84-1.85.
  The rolling window drops old v1 days while v2 days arrive, so v2 cannot be isolated from the
  review (see 3.1). It is no better than the line overall.
- Shots: v2 rows 784 → 878 → 1,035, never graded anywhere visible (see 3.2).
- That matches #183's own backtest: "No edge threshold cleared breakeven with its interval"
  (`betting_edges.py` docstring). Shots MAE 1.304 vs line 1.303, totals corr 0.134 vs 0.140, and
  saves were never tested against lines. The plumbing is now right. **The model is a mean
  estimator that tracks the line at best.** That answers "why NHL misses": there is no edge to
  find with these features.

**What is still wrong.**
1. **The 05:00 run writes a week of games.** `get_schedule(date)` returns a 7-day `gameWeek`
   (`_boxscore.py:30-45` says so), and `_run_daily_core` takes every game in it
   (`daily_predictions.py:655-667`). Only the 16:45 refresh filters to today (`:756-762`). The
   comment in `generate_daily_predictions.py:172-173` ("the NHL schedule endpoint already filters
   to today's games") is wrong. Effects: one event-odds call per future game every morning (about
   40 events, roughly 40-80 credits a day for totals lines that are rewritten each day); NHL API
   roster bursts; future-dated rows in the 30d version counts (118 v2 goalie rows existed on 11-15
   after one v2 slate, R15:83). It also delays the run, so the 10-minute odds cache
   (`generate_daily_predictions.py:28`) can expire between the goalie, shots and totals phases and
   refetch. CODE-ONLY on the credit size; the counts in R15 agree.
2. **Matinees and early games are never refreshed** (bd YetAI-ph9). The 16:45 refresh takes only
   FUT/PRE games, so games starting before 16:45 ET (weekend and holiday matinees, e.g. Black
   Friday 11-27) keep the 05:00 row: an ESPN "expected" starter or none, and props lines that
   are usually not posted at 05:00. The 11:00 auto pick would read those rows. There is also no
   unique (game_date, team_id) index on goalie predictions (ph9). For 19:00+ games, 16:45 is
   adequate.
3. **Shots carry no prices** (no over/under odds columns on `pred_nhl_player_shots_predictions`),
   and every NHL line is DraftKings-only. Calls are graded at an assumed −110 (register X-3).
4. **Are NHL calls shown to users while in shadow?** As labelled picks, no. The live board strips
   `betting_recommendation`, `recommendation`, `value_tier` and `edge_category` for withheld keys
   (`predictions.py:168-173, 1072-1073`), and the prove-in gate withholds auto picks
   (`record_gate.py:147-162`). But `edge` (totals), `edge_saves`, `confidence` and projection vs
   line stay in the payload, so the lean is visible. Past slates show the graded shadow calls, by
   design. CODE-ONLY on what the UI renders.

**Confidence.** CONFIRMED (model has no edge against the line; register fixes verified). Item 1
is CONFIRMED in code, its credit size is HYPOTHESIS. Settle with:
```sql
SELECT p.model_version, count(*) calls,
       avg(((p.betting_recommendation LIKE 'OVER%') = (a.actual_shots > p.shots_line))::int) hit
FROM pred_nhl_player_shots_predictions p
JOIN pred_nhl_player_shots_actuals a USING (player_id, game_date)
WHERE p.game_date >= '2026-11-14' AND p.betting_recommendation ~ '^(OVER|UNDER)'
  AND a.actual_shots <> p.shots_line GROUP BY 1;
SELECT prediction_date::date run_day, count(*), min(game_date), max(game_date)
FROM pred_nhl_team_totals_predictions WHERE prediction_date >= '2026-11-15' GROUP BY 1;
```

**Status.** NHL-1/5/6/7: fixed and verified. NHL-2/3/4: listed and still open (no edge).
Items 1 and 4: new. Item 2: ph9, listed and still open.

**Fix.** (S) Filter `_run_daily_core` games to `game_datetime_et(g)[0] == slate_date`, as
`run_goalie_refresh` does. (S) Add a 12:00 ET NHL refresh, or one 2 h before the first puck, for
matinees. (S) Strip `edge`/`edge_saves` in `_NO_PICK` for withheld groups. (M) Stop spending
effort on NHL calls until a feature that the line does not already price (confirmed lineups,
goalie pulls, back-to-backs) passes the backtest.

---

## 5. Scheduling: picks are made before the refreshes that feed them, and long ETL jobs can re-run 24 h later

**Beat schedule (ET, Celery tz America/New_York; `celery_app.py`):**
| Sport | Projections built | Lines fetched | Pregame refresh | Grading / actuals | Auto picks |
|---|---|---|---|---|---|
| NBA | 03:30 full pipeline (54-104 min, no `expires`) | 03:30, 12:00, 17:00 (7 prop markets, 10 books); close capture for reb/ast 15-25 min before tip (11:00-23:50, every 10 min, bets queue) | 12:00, 17:00 (injuries, minutes, lines, all projectors; expires 2 h) | 03:30 (store actuals + grading); 05:05 spreads accuracy; fair-price grade 08:30 (7-day lookback); settle every 15 min | 11:00 (reserve 1), 17:30 |
| NHL | 05:00 (ingest, actuals, predictions for the whole week) | 05:00, 16:45 (DraftKings only) | 16:45 (FUT/PRE games of today) | 05:00 actuals over the shared grading window | 11:00, 17:30 (prove-in withheld) |
| NFL | 04:30 daily | 04:30; Tue-Fri 11:00 anytime TD | Sun 10:00/12:30/15:30, Mon 18:00, Thu 10:00/19:00, Sat 12:30 | 04:30 | 11:00, 17:30 |
| All | | games cache 06:00/14:00/22:00 | | review 09:45, credits alert 09:40 | |

**Problems.**
1. **The 11:00 auto pick runs before the 12:00 NBA refresh.** It reads 03:30 projections. The
   code's own comment says props are mostly not posted by 03:30 (`etl_pipeline.py:543-546`), and
   the 03:30 injury and minutes inputs are 7.5 h old. With `reserve_slots=1`, every pick but one
   is made on that board. CONFIRMED (schedule). Fix (S): move `nba-pregame-refresh` to
   `hour=[10,17], minute=0` (or 10:15), or move the first pick run to 12:45.
2. **17:30 pick vs 17:00 refresh after the bets-worker split.** Before #185 the single
   concurrency-1 worker made the 17:30 pick wait behind the 17:00 refresh: an accidental but
   correct ordering. With `CELERY_ROLE=etl` and `bets`, the pick runs on its own worker at 17:30
   while the refresh may still be upserting players one commit at a time
   (`generate_points_predictions.py:85-155`). The pick then reads a mix of 12:00 and 17:00 rows.
   No freshness or lock check exists in `auto_pick/` (grep: no `projected_at` use). CODE-ONLY:
   whether the rollout's Step 4 is live is not visible from here. Fix (S): the evening pick
   checks a Redis "nba_refresh_running" key that the refresh sets and clears (retry in 5 min), or
   the refresh enqueues the pick when it finishes.
3. **The NFL Monday 18:00 and Thursday 19:00 availability runs come after the last pick of the
   day (17:30)**, so MNF and TNF picks never see them. Inactives (90 min before kickoff) are never
   seen at all. CONFIRMED (schedule). Fix (S): add a Mon/Thu 19:15 ET auto-pick run (NFL only), or
   move those refreshes before 17:30.
4. **Long beat jobs have no `expires`**: `nba-update-pipeline-daily`, `nfl-update-pipeline-daily`,
   `nhl-update-pipeline-daily`, `nba-spreads-accuracy-morning`, `model_review_daily`,
   `odds_credits_runout_alert` (`celery_app.py:114-117, 162-171, 215-218, 339-348`). With
   `task_acks_late` and `visibility_timeout=86400` (`:46-52`), a run killed by a deploy comes back
   24 h later. bd YetAI-r8n shows the NBA pipeline started twice, 24 h apart, at 21:37-22:52 UTC
   (16:37-17:52 ET), which is exactly when it blocks the 17:00 refresh and the evening pick inputs.
   r8n frames this as a manual-enqueue problem; the beat entries are exposed too. Fix (S):
   `"options": {"expires": 6*3600}` on each.
5. bd YetAI-53h (NBA pipeline never records FINISHED): still open. Pipeline-health alerts are
   blind for the most important pipeline. Not re-diagnosed here.
6. Minor: `docs/runbooks/bets-worker.md` lists every task routed to `yetai_bets` except
   `fair_price.shadow_flag` (`celery_app.py:77`). It runs every 10 min on the same
   concurrency-1 bets worker as settlement and picks.

**Status.** 1-3: new. 4: r8n listed and still open (the beat-entry exposure is new). 5: 53h open.

---

## 6. Odds API credits: the review's section is meaningless on GitHub; the counter works where it runs, and the plan lasts

**What is wrong.** The review prints "Odds API budget counter unreachable (Redis); calls are NOT
being capped or counted" and "remaining n/a; yesterday recorded 0; 7d rate 0/day" (R17:185-186,
338-343). That comes from the GitHub runner, which has `DATABASE_URL` only: no Redis
(`localhost:6379` refused) and no `ODDS_API_KEY`. `_credits_section`
(`model_review_service.py:1089-1096`) reads Redis (`odds_api_budget._usage`, fail-open at
`odds_api_budget.py:132-145`) and the live quota. Neither works there, so every figure is
0 or n/a, and the warning describes the runner, not production. The production path is the
Celery `model_review.daily` email at 09:45 ET (`tasks/model_review.py`) on the worker, which has
Redis. Every Odds API call routes through `sync_odds_get`/`async_odds_get` (grep: the direct
`aiohttp` users all call `async_odds_get`). So the email shows real numbers, but nothing in the
evidence confirms it.

**Daily burn estimate from the schedule** (billed = markets returned × regions; 10 books = 1
region, confirmed in `_fanduel_lines.py:31-36` and the backtest doc):
- NBA: 3 runs × 7 markets × ~7.5 events ≈ 160 (less at 03:30, when few props are posted), close
  capture 2 × 7.5 ≈ 15, game lines 3 × 3 ≈ 9. **About 150-185.**
- NHL: 05:00 run ≈ 7 games × 3 + ~40 future games × ~1 (item 4.1) ≈ 60, up to about 120 if the
  10-min cache expires between phases; 16:45 refresh ≈ 21. **About 80-140.**
- NFL: QB yds, receiving yds and anytime TD per event plus game lines ≈ 45 a day, plus midweek TD
  and gameday runs. **About 50-100.**
- Games cache: 3 × 4 sports × ~3 ≈ 36. User-facing API calls: unknown.
- **Total about 320-460 a day.** At most the 500/day cap (`ODDS_API_DAILY_BUDGET`) allows 15,000
  over the 30 days from 11-14. About 31,400 were left on 11-14 (`docs/edge-engine-backtest-2025-26.md:31`),
  so **the plan lasts to the 12-14 reset with about 15,000-20,000 to spare.**

**The real risk is the daily cap, not run-out.** The counter key is the UTC day
(`odds_api_budget.py:39-40`), which resets at 19:00 ET. The last jobs inside a UTC day are the
16:45 NHL refresh, the 17:00 NBA refresh and close captures for tips before 19:00. On a heavy day
(big NBA and NHL slates plus an NFL Sunday) those are the calls refused once 500 is reached. They
feed the 17:30 picks and the CLV closes. HYPOTHESIS. Settle in production: worker logs
`grep "daily budget reached"`, or Redis `HGETALL odds:budget:callers:<UTC day>` and
`GET odds:budget:credits:<UTC day>` for the last 7 days.

**Confidence.** CONFIRMED that the GitHub section is empty for environmental reasons (code plus
the error text). HYPOTHESIS for the burn figures and the cap starvation.

**Status.** New. #188 claimed the credits section; it works only where Redis exists.

**Fix (S).**
- When Redis is unreachable, `_credits_section` returns
  `{"unavailable": "no Redis in this environment; see the 09:45 email"}` instead of zeros.
- Either give the workflow read-only `REDIS_URL`/`ODDS_API_KEY` secrets, or drop the section
  from the CI run.
- Raise the cap to about 800, or key the budget to the ET day so the evening jobs are not last
  in line. Also filter the NHL 05:00 run to today (item 4.1), which saves about 40-80 a day.
