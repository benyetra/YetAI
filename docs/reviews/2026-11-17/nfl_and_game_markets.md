# NFL projections and game-market anchoring: findings (review 2026-11-17)

Reviewer area: NFL QB passing yards, receiving yards, anytime TD, kickers, spread, total, win
probability, and the market anchor for game markets (NBA #181, NFL/MLB still open in bd YetAI-ld0).
Code at origin/main 5b662edf. Production numbers come only from `evidence/daily_review_2026-11-1{4..7}.txt`
and GitHub Actions run 42896579873 (NFL Prod QB eval, 11-10).

## Read this first: the week number in the brief is off by one

The games played 11-12 to 11-16 are **week 10**, not week 11. The public nflverse schedule
(`nfldata/data/games.csv`) lists them as week 10, and the code agrees:
`get_current_nfl_week(2026, today=2026-11-12..18) == 10` (reproduced; first Thursday is 2026-09-10,
`backend/app/services/etl/nfl/nfl_common.py:30-54`). Week 11 starts Thursday 11-19. So there is exactly
**one** clean post-freeze NFL week so far (week 10, boards built from 11-12 on), not two.
The register's "week-10 board" (NFL-9) means these same games.

## Isolating week 10 from the daily diffs

The 30-day window is `[today-30, today-1]` by game date (`model_review_service.py:1099-1108`). Between the
11-15 and 11-17 reports the window drops 10-16 and 10-17 (no NFL games) and adds 11-15 (Sunday) and 11-16
(MNF). The day-over-day differences are therefore exactly the 13 week-10 Sunday and Monday games (TNF 11-12
was already in the 11-14 report):

| Market | Week 10 (Sun + Mon) | 30-day line in 11-17 report | 90-day gate record |
|---|---|---|---|
| Spread calls | **0 of 5** hit; bias +6.3, MAE 13.1 vs line 11.2 (13 games) | 9/29, 31.0% | 25/56, 44.6% |
| Total calls | 5 of 8 hit | 22/38, 57.9% | 32/71, 45.1% |
| QB passing yards | **0 calls**; 23 rows, model MAE 66.5 vs line 67.0, bias -11.5 | 6/18 (all from older rows) | 22/46, 47.8% |
| Receiving yards | not graded yet (see F3) | n=21, no calls | n/a |

(Derived from n × mean in each report. For example QB: 129×55.60 − 108×54.01 = 1339 over 21 rows, so MAE 63.8;
the line gives 129×47.59 − 108×44.43 = 1341, so 63.8.)

---

## F1. Users still see NFL spread, total, receiving-yards and anytime-TD picks for markets that measurably lose; the gate withholds them only from auto picks

**What is wrong.** The `/predictions/nfl` endpoint returns every stored `recommendation` /
`betting_recommendation` unchanged. It never calls `_withhold_unproven_picks`, which NBA and NHL do. So paid
users see HOME/AWAY, OVER/UNDER and "No TD" picks for NFL spread, NFL total and NFL passing yards, all three
WITHHELD by the record gate. They also see picks for receiving yards and anytime TD, which the gate does not
track at all.

**Evidence.**
- `backend/app/api/v1/predictions.py:918-988`: the NFL handler has no `_withhold_unproven_picks`. Compare
  NBA at `:907-914` (which covers only steals and blocks) and the helper at `:192-223`.
- The frontend renders the picks: `frontend/src/lib/mergeSpreadTotalsGameProjections.ts:51-70` (spread and
  total pick), `frontend/src/lib/propProjectionDisplay.ts:365-373,408-416` (receiving and QB "Pick"
  column), `frontend/src/lib/anytimeTdDisplay.ts:95-98` (ATD pick). The ATD UI is on by default
  (`anytimeTdDisplay.ts:20-26`).
- Even if the backend nulled the spread pick, the UI would put it back.
  `frontend/src/components/yetai/MlbGameProjectionsGrid.tsx:125-139` (`spreadRecommendation`) falls back to
  `projected_margin` vs `market_spread` at `spreadEdgeThreshold` (3.0 for NFL, `:80-84`; 2.0 for NBA/WNBA).
- Gate (11-17): `WITHHELD NFL/spread ... projections 25/56`, `WITHHELD NFL/total ... 32/71`,
  `WITHHELD NFL/player_prop/passing_yards ... 22/46`. Week 10 spread calls went 0/5 (table above).

**Why it makes picks miss.** These labels are the only "YetAI picks" an NFL user sees: the NFL page has no
Best Edges section, and there are no NFL auto picks in the 30-day bet record. Every label shown comes from a
market at or under 45% over 90 days, or one with no graded record.

**Confidence.** CONFIRMED (code path plus the gate numbers).
**Register status.** New. The register assumed the gate covers the board ("the board applies the same rule",
`record_gate.py:24-25`). That holds for NHL and for NBA steals/blocks only. The same gap exists for NBA
points/threes (withheld by the gate, still labelled on the board); that belongs to the NBA props reviewer.
**Fix (S).** In `nfl_predictions` wrap the payload in
`_withhold_unproven_picks(payload, db, {"spreads": ("NFL","spread",None), "totals": ("NFL","total",None), "qb_predictions": (...passing_yards), "receiving_yards_predictions": (...receiving_yards)}, loaders=("nfl",))`.
Add `anytime_td_predictions` with an unconditional strip (it has no gate key; see F4). In
`MlbGameProjectionsGrid.tsx:spreadRecommendation`, stop deriving a side when the stored recommendation is
absent. Touch two files.

## F2. NFL spread is still raw Elo on the basketball config, unanchored, and still makes calls; win probability comes from the same biased margin

**What is wrong.** `elo-pace-v1` is a shared basketball Elo with home advantage 2.5, K 20 and the WNBA
season-start month. It adds a points-per-game overlay and calls HOME/AWAY whenever it disagrees with the line
by 3 points. Nothing pulls it toward the market.

**Evidence.**
- `backend/app/services/etl/_spread_model.py:11-35`: `NFL_CONFIG = SpreadLeagueConfig(home_court_advantage=2.5, edge_threshold=3.0)`.
  It inherits `season_start_month=5` and `pace_overlay_factor=0.15`, and the module docstring says it is
  "for basketball leagues".
- `backend/app/services/etl/nfl/spread_projector.py:100-150` computes `projected_margin = elo + pace + qb_out`
  and calls `spread_recommendation` against the raw margin. The version stamp is at `:210`.
  `home_win_prob = margin_to_win_prob(projected_margin)` (`:121`), so win probability carries the same bias.
- 11-17 report: `NFL/spread: 9/29 calls 31.0%; bias +3.81, MAE 10.76, line MAE 9.37 (n=70)`. Week 10:
  bias +6.3, model MAE 13.1 vs line 11.2, 0/5 calls. Versions: `pred_nfl_spread_projections: {'None': 57, 'elo-pace-v1': 26}`.
  The 26 rows are the week-10 and week-11 boards, so this is what runs now.

**Why it misses.** The projected margin overstates the home side by about 4 points on average (bias is
projection minus actual). The 3-point threshold mostly fires when Elo disagrees with the market. That
disagreement is mostly the bias, so calls lean HOME and lose. The model is 1.4 points of MAE worse than the
line, so anchoring with a fitted weight would put the weight near 0.
**Confidence.** CONFIRMED.
**Register status.** NFL-7: listed and still open (bd YetAI-ld0).
**Fix (S).** Reuse `backend/app/services/etl/nba/market_anchor.py` (`fit_anchor` / `anchored`), which is
pure and sport-agnostic. Publish `market + a + k·(elo − market)` fitted on graded NFL rows, gate calls with
`totals_baseline.recommend`, and derive win probability from the anchored margin. Until that ships, set the
NFL recommendation to NO_PLAY. Verdict: **fine plumbing, no edge**. The model is worse than the line, and the
home bias is the specific reason it misses.

## F3. Receiving yards: the only graded rows compare week-10 lines with week-9 yards, the real week-10 board is not graded until 11-19, and the call logic leans over by construction

**What is wrong (measurement).**
1. The `n=21` graded rows (unchanged 11-14 to 11-17, identical bias +1.81 and MAE 15.21) are the 26
   `recv_nonml_v1` rows written on Tuesday 11-10 by #165/#169. That code had no schedule filter, so it
   labelled the rows with the current week (9) and `game_date = today`, and attached the lines on offer
   that day, which were for week-10 games.
   `collect_recv_yds_actuals.run` grades `current_week − 1`. From 11-12 that is week 9, so these rows were
   graded against week-9 games that were played *before* the line existed. The 15.21 vs 21.50 "model beats
   the line" result is meaningless.
2. The 188 `recv_nonml_v2` rows are the week-10 board. They stay ungraded until Thursday 11-19, when
   `current_week` rolls to 11 (`nfl_common.py:41-54`). Unlike QB (`collect_qb_actuals.py:419-423`, H-8),
   the receiving grader does not also try the current week, so the board is graded 3 to 4 days late. If
   nflverse were late it would also get only a 7-day retry window. Grading is lagging, not broken.

**What is wrong (model).** Calls compare a *mean* projection (targets × yards per target) with a sportsbook
line that sits near the *median* of a right-skewed distribution. The anchor is `0.25·model + 0.75·line`
(`recv_yds_model.py:7,66-80`), and a call needs |published − line| ≥ 7% of the line
(`recv_yds_betting.py:16-19,59-112`). So a call fires only when the model mean is at least 28% above or below
the line. Skew makes "above" far more common than "below", which explains the 60 overs to 3 unders on the
week-10 board (register NFL-9). Neither side has any median, skew or P(over) step.

**Evidence.** `git show 8d7610c5:backend/app/services/etl/nfl/recv_yds_usage.py` (`load_usage_priors_for_names`
passes no schedule, `game_date=date.today()`); the schedule filter arrived in #170 (986d309f, 11-10 15:13),
which is also when v2 was tagged. `backend/app/services/etl/nfl/collect_recv_yds_actuals.py:104-105`
(`week = current_week − 1`). Reproduced: `get_current_nfl_week(2026, 2026-11-10) == 9`, and `== 10` from
11-12. Evidence files: `NFL/player_prop/receiving_yards: 0/0 calls n/a; bias +1.81, MAE 15.21, line MAE 21.50 (n=21)`
on all four days; `pred_recv_yds_predictions: {'recv_nonml_v1': 26, 'recv_nonml_v2': 188}`.

**Why it misses.** No graded record exists yet for the published model. The over lean means the calls
users see (F1) are mostly OVERs priced at the median. Those win about half the time at best, which is below
breakeven at the vig.
**Confidence.** Mislabel: CONFIRMED by code and dates, with one SQL to close it:
`SELECT p.week, p.game_date, p.model_version, date(p.created_at), count(*) FROM pred_recv_yds_predictions p JOIN pred_recv_yds_actuals a USING (season, week, player_id) WHERE p.season=2026 GROUP BY 1,2,3,4;`
(expected result: week 9, game_date 2026-11-10, v1, about 21 rows). The skew mechanism is HYPOTHESIS. On
11-19 run `SELECT avg(actual_receiving_yards > ou_line) FROM pred_recv_yds_actuals WHERE week=10;` and the
median of `model_yards − ou_line`. If overs hit under 50% while the model mean is above the line, the
mechanism holds.
**Register status.** NFL-9: listed and open, but the "n=21" record is a new measurement bug.
**Fix (S).** (a) Delete or exclude the 26 v1 rows (`model_version='recv_nonml_v1'`) from grading and the
review. (b) Grade `current_week` as well as `current_week − 1`, the same as QB. (c) Make no receiving call
until week 10 and 11 are graded. Then either subtract the measured model-minus-line offset per position, or
call from P(yards > line) under a skewed (for example gamma) distribution. Verdict: **plumbing broken
(measurement), too little data on the model**.

## F4. Anytime TD is graded but never reviewed or gated, still publishes OVER and "No TD" calls, keeps the biased position priors, and is the one NFL market whose rows are not frozen at kickoff

**What is wrong.**
- It is missing from the report, not ungraded. `anytime_td_actuals` runs in the NFL actuals phase
  (`etl_pipeline.py:812-820`), but neither `model_review_service.LOADERS` (`:359-365`; `_nfl` at `:284-356`
  has no ATD) nor `record_gate._nfl` / `emitted_keys` (`record_gate.py:396-503`) includes ATD. The 902 rows
  in 30 days are invisible to the daily review and have no gate key.
- Calls are still published (bd YetAI-mgo not done). `anytime_td_market_anchor.py:133-144`: OVER when
  edge ≥ 0.05 and EV > 0, "UNDER" (No TD) when edge ≤ −0.05, with no price or EV check on the No side.
  `anytime_td_betting.py:118-167` writes them, and the board shows them (F1).
- The NFL-4 priors are unchanged. `anytime_td_features.py:40-51`: QB share 0.07 × conversion 0.14, so
  P(TD) is about 0.03 against the 0.172 observed. The market blend keeps `w = 0.05 + 0.85·signal` of the
  model (`anytime_td_market_anchor.py:113-117`). Signal rises by 0.35 for questionable players and by 0.15
  each for mid-season, RZ and GL volume (`:47-110`), so a typical mid-season starter keeps about 40 to 60%
  of a model that runs low. That pushes p_publish below the fair price and produces "No TD" calls. The
  calls cluster on questionable players, where the weight on the biased model is highest.
- Freeze. `anytime_td_projector.py:158-162,276-312` and `anytime_td_betting.py:470-485` freeze only rows
  whose `game_date < today`. The Sunday 12:30 and 15:30 ET gameday runs (`celery_app.py:180-189`) therefore
  re-project and re-price rows for games that already kicked off that day (the London 9:30 game, then the
  1 pm slate). `delete_stale_week_predictions(on_or_after=today)` can delete a started game's row when a
  player drops off the slate mid-game, which removes losing calls from history. The Odds API `/events` feed
  includes in-play events, so live ATD prices can be attached.

**Why it misses.** The published probability is a market price pulled down by a biased model. The calls
are the bias, not information, and nothing in the daily review would show it.
**Confidence.** Missing from the review/gate and still calling: CONFIRMED (code). Bias size: CODE-ONLY here
(the register measured it; no ATD numbers in the evidence). Post-kickoff rewrite: CODE-ONLY. To settle it:
`SELECT count(*) FROM pred_nfl_anytime_td_predictions p JOIN pred_nfl_game_lines g ON g.game_date=p.game_date AND p.team_name IN (g.home_team_name, g.away_team_name) WHERE p.season=2026 AND p.week=10 AND ((p.features->>'market_as_of')::timestamptz > g.game_time AT TIME ZONE 'UTC' OR p.prediction_date > g.game_time);`
**Register status.** NFL-4: listed and open. Missing from the review/gate: new. X-6 "fixed in every
sport": claimed fixed but not actually fixed for ATD.
**Fix (S).** Set `recommendation_for_market_edge` to return NO_PLAY (or strip it on the board). Add an
`("NFL","player_prop","anytime_td")` loader to `model_review_service` that reports Brier against the market
fair price. Freeze by kickoff with `has_kicked_off` using the nflverse `gameday`+`gametime` already loaded
for features, and limit the stale delete to unstarted games. Recalibrating the priors is M. Verdict:
**plumbing broken (freeze, review), no edge**.

## F5. NFL totals: 57.9% at n=38 is noise; over 90 days it is 45%, and the model is the same unshrunk PPG average

**What is wrong.** `ppg-blend-v1` is `(own PPG + opponent PPG allowed)/2` per side with no shrinkage and no
market term. It calls at |edge| ≥ 3 (`backend/app/services/etl/nfl/totals_projector.py:29-83`). The
30-day 22/38 has a Wilson 95% interval of about [42%, 72%] (z = 0.68 against 52.4%). The previous 30 days
were about 32% (hit trend +25.8 points), and the gate's 90-day record is 32/71 = 45.1%. Week 10 was 5/8. MAE
10.70 vs line 10.03: the model is still worse than the line.
**Why it misses.** A raw average is noisier than the line, so most edges at 3 points or more are noise, and
the larger ones (NFL-8) are the noisiest.
**Confidence.** CONFIRMED (numbers in the 11-17 report and the gate).
**Register status.** NFL-8: listed and open (bd YetAI-ld0 / YetAI-mgo).
**Fix (S).** The same anchor as F2. Verdict: **fine plumbing, no edge** (the 30-day hit rate is too little
data, and the longer record loses).

## F6. QB passing yards: the published number is the line plus noise, so no calls are made; the 6/18 is history, and the promote gate's "beats the line" is a measurement artifact

**What runs.** `NFL_QB_ML_ENABLED` is on (`gbm-qb-residual-2026`: 160 rows against `tier-v3`: 7). With the
flag on, `published_qb_yards` returns the residual GBM as is, so the soft anchor is bypassed
(`backend/app/services/etl/nfl/qb_passing_yards_ml.py:289-317`). The 11-10 model is a market-residual GBM
(`baseline_mode: market`, `strong_reg`: depth 2, 80 trees, learning rate 0.04). Its output is the line plus a
few yards, so `|edge| < 7%` and every row is PASS (`qb_betting.py:116-161`). Week 10 had 23 graded rows and
**0 calls**, with model MAE 66.5 vs line 67.0. The soft anchor (`α=0.25`) only applies with the flag off.

**Classifier-only path.** Gone. `qb_betting.py:152-161` returns PASS below the yards edge, and the
classifier can only veto (`:180-195`). `qb_betting.py:394` is the only writer of `betting_recommendation`.
Fixed and verified.

**Measurement bug in the promote gate (run 42896579873).** `mae_lift_vs_line 0.085` compares ML 57.04 with
`line_only` 62.34. That line baseline includes 52 holdout rows with no line and 147 rows with a "historical
index" line. On rows with a real line, `line_only_real_rows: mae=55.144`, which beats the ML's 57.04.
`ou_status acc 0.5195` is below the 52.4% breakeven. `promote_recommended: True` was therefore issued for a
model that does not beat the line, and production agrees: 30-day MAE 56.20 vs line 48.39.

**Still open (NFL-3 follow-ups).** `qb_dynamic` overwrites `predicted_passing_yards` before kickoff without
clearing `betting_recommendation` (`qb_dynamic.py:784-806`). If the later `qb_betting` run finds no line,
the row shows a call made on different yards. Any exception in the ML block is swallowed
(`qb_betting.py:369-370`), which keeps the tier yards and still writes a call. `.limit(32)` is still at
`qb_betting.py:239-244,256-261`. `has_kicked_off(None)` is False (`nfl_common.py:66-81`), so a QB whose
kickoff lookup fails is never frozen. `model_version` is still `String(20)`: `gbm-qb-residual-2026` is
truncated, so v5 and v6 rows cannot be told apart (NFL-10).

**Why it misses.** It does not miss on calls any more, because it makes none. The 33% is all rows from
weeks 6 to 9, built before the freeze and graded against rewritten lines. Users see a number that is the
line, labelled as a model projection.
**Confidence.** CONFIRMED (code, the eval log, and the week-10 diff).
**Register status.** NFL-1: fixed and verified. NFL-2: still open and now measured (week 10: model ≈ line,
no calls). NFL-3 follow-ups and NFL-10: still open.
**Fix (S).** Fix the gate: compare against `line_only_real_rows` and require the ML holdout MAE on the same
real-line rows to beat it. Under that rule the 11-10 model should not have been promoted. Then either flip
`NFL_QB_ML_ENABLED` off (the soft anchor publishes) or keep it on as a line-tracker and say so. In the
`qb_dynamic` update path, clear `betting_recommendation`, `bet_size` and `edge_percentage`. Verdict: **fine
plumbing (mostly), no edge**. bd YetAI-bzv can be decided on week 10 plus 11, not on the 30-day number.

## F7. NBA game-market anchor (#181): implemented correctly and cannot publish calls; review sign conventions disagree between scripts

**Checked and correct.**
- Line and timing. Both projectors read `NBAGameLines.total` / `spread_home` at run time, only for games
  not yet started (`totals_projector.py:925-948`, `spread_projector.py:164-170`), and store that line on the
  row. The anchor history uses the stored row line, falling back to the lines table
  (`totals_projector.py:551-615`).
- No line at projection time. `anchored()` returns the model (`market_anchor.py:69-73`). For totals that is
  the corrected baseline (`baseline + recent_bias`), not the old pace/ORtg model, unless there is no history
  (`totals_projector.py:699-713`). `edge=None` gives `NO_PLAY` (`:737-748`). For spreads,
  `spread_recommendation(None)` also gives NO_PLAY, and the UI cannot derive a side without a market. No
  biased call publishes. The displayed number is unanchored only in that case.
- Drift. The fit uses the last 150 graded games including last season (`opener_prev`), with ridge priors
  of 200 games (totals) and 400 games (spread) toward k=0 and 100 games toward a=0. k is clamped to [0, 1]
  (`totals_baseline.py:62-64`, `spread_projector.py:53-54`, `market_anchor.py:33-66`). Reported n is 150 and
  190 to 212, and k stays at 0.0 to 0.048. Tiny-sample drift is not possible.
- Calls. `recommend` needs 30 graded would-be picks of this version (`totals_baseline.py:191-229`). With k
  about 0 the edge is about a (+0.16), which never reaches 4.0 or 2.0, so the version can never build a
  record. NBA game calls are permanently off: safe, and a dead end by design.
- `spread-anchor-v1 MAE 12.59 = line MAE 12.59` is exactly k=0, a=0 (spread fits no constant). Totals
  bias −6.40 on 22 games equals the projection's (≈ line + 0.16) error, so the market was about 6.5 low on
  those games.

**Sign conventions (measurement).** `scripts/nba_totals_backtest.py:124` uses `e = actual − projection`
(so "+4.67" means projections are 4.67 low). `model_review_service.stats` uses `proj − actual`
(`model_review_service.py:418`), so "−4.51" means the same thing. The rows also differ: 191 graded games
with a line for the whole season, against 183 "version none" rows in the 30-day window. They agree; only the
labels conflict. `nba_props_audit` prints "(actual-proj)"; model_review prints just "bias".
**Fix (S).** Print "bias (proj − actual)" in `render_text`, or flip the backtest so all three scripts share
one convention.

**Latent leak.** The frontend re-derives a spread side at |projected − market| ≥ 2.0 for NBA (F1). It is
harmless while k=0, but a future k > 0 would show picks the backend withheld.
**Confidence.** CONFIRMED (code). **Register status.** NBA-6/7: fixed and verified for NBA. NFL and MLB
remain open (bd YetAI-ld0); NHL totals has no anchor (55/116, 47.4%).

## F8. Kickers are still surfaced with no signal and no review

`/predictions/nfl` returns `kicker_predictions` with a date fallback to the latest row per kicker
(`predictions.py:954-964`, `_query_nfl_latest_deduped` `:337-355`), which can show stale rows. The NFL page
renders FGA/FGM/Hit% (`frontend/src/app/predictions/nfl/page.tsx:25-32,42-46`). There is no pick column and
no line, so nothing loses money, but the numbers have about zero correlation (NFL-6). Kickers have no
`model_version` and appear nowhere in the daily review. **Confidence.** CONFIRMED (code). **Register
status.** NFL-6: listed and still open. **Fix (S).** Remove the kicker group from the NFL page (one array
entry) until the model uses game context.

---

## Row freezing at kickoff/tip (X-6)

| Writer | Freeze rule | Verdict |
|---|---|---|
| NFL spread / totals (`spread_projector.py:63-68`, `totals_projector.py:163`) | `not_started(game_time UTC)`; missing time means the next ET day | OK |
| NFL QB yards (`qb_dynamic.py:669`) and line/call (`qb_betting.py:288-290`) | nflverse kickoff | OK, except a `None` kickoff never freezes, and a pre-kickoff yards change keeps the old call (F6) |
| NFL receiving (`recv_yds_usage.py:339-375`) | Schedule filter by kickoff (verified locally: a game at 20:15 is excluded at 21:00) | OK |
| NFL anytime TD (`anytime_td_projector.py:276-312`, `anytime_td_betting.py:470-485`) | **date only** | **Not frozen on game day** (F4) |
| NBA totals / spread (`totals_projector.py:933-934`, `spread_projector.py:170`) | `not_started(game_time)` | OK; actuals copy the stored projection and line (`totals_accuracy_tracker.py:228-231`), so no later line is attached |

## Per-market verdicts

| Market | Verdict | Specific reason it misses | Smallest fix |
|---|---|---|---|
| Spread | Fine plumbing, no edge | Raw basketball-config Elo, home bias +3.8 (week 10 +6.3), calls on disagreement with the line | Anchor with `market_anchor.fit_anchor`; NO_PLAY until then |
| Win probability | Fine plumbing, no edge | Logistic of the biased margin | Derive from the anchored margin |
| Total | Fine plumbing, no edge (30-day hit rate is noise) | Unshrunk PPG average, worse than the line | Same anchor |
| QB passing yards | Fine plumbing (mostly), no edge | ML is the line plus noise; promote gate compared against a line baseline padded with missing/imputed lines | Fix the gate's line baseline; flag off or keep as a tracker; clear the call on re-projection |
| Receiving yards | Plumbing broken (measurement), too little data | Graded rows mislabelled; real board graded only on 11-19; mean-vs-median over lean | Drop the v1 rows, grade the current week too, re-centre or use P(over) |
| Anytime TD | Plumbing broken (freeze, review), no edge | Biased priors; No-TD calls without prices; not frozen on game day; not in review or gate | Stop the calls, add a review loader, kickoff freeze |
| Kickers | No signal | No game context | Hide |

## What a user can still see as a call for a market that measurably loses

1. NFL spread HOME/AWAY pick on the game cards (30 days 31%, 90 days 45%, week 10 0/5). The backend never
   strips it, and the UI re-derives it at |edge| ≥ 3.
2. NFL total OVER/UNDER on the game cards (90 days 45%).
3. NFL anytime-TD OVER / "No TD" pick column. It is ungraded in the review, and the register measured it as
   adding nothing beyond the price.
4. NFL receiving-yards OVER/UNDER pick column and top-play highlight (week-10 board 60 overs to 3 unders,
   no valid graded record).
5. NFL QB OVER/UNDER: the column exists, but the current model produces only PASS.
6. Outside this area: NBA points and threes are WITHHELD by the gate but still labelled on the NBA board,
   because `_NBA_NEW_MARKET_KEYS` covers only steals and blocks.
