# Projection issues register (2026-11-13)

Every known problem with the YetAI projections, with the evidence, the cause, the remedy and whether
PR #177 already covers it. Built from three code audits and a read-only measurement of every market
against production results on 2026-11-13.

## Bottom line

No market in any sport beats the betting line today. Three markets are about even before the real
price (NBA rebounds, assists and threes), and even those sit below the breakeven the stored prices
imply. The largest causes are data and plumbing faults that feed the models wrong inputs, not the
model formulas:

1. **NBA box scores are filed a day late and duplicated in history** (NBA-1). About a third of this
   season's stored NBA prop grades are against the wrong game, and the same rows feed rest,
   back-to-back and Vegas-line features in training and serving.
2. **Every NHL model input is stale** (NHL-1). Team stats come from preseason games only, and game
   and goalie history stopped updating on 2025-11-22.
3. **NFL history before 2026-11-10 was rewritten after kickoff** (NFL-3, NFL-5), so most stored NFL
   records cannot be trusted and need re-measuring from week 10.
4. **Adjustments layered on top of baselines add error** (NBA-2, NBA-3, NHL-2, NFL-8): rest, form,
   injury, ice-time and home multipliers carry no signal against a market that already prices them.

PR #177 fixes tracking, grading, freezing and the retrain loop. It does not make any model beat the
market. The items marked "not addressed" below are the work that would.

## How this was measured

- Production database, read-only, 2026-11-13. Current season per sport; MLB and WNBA are a look
  back at their 2026 seasons.
- Everything is regraded from the raw projection, the stored line and the raw actual. Stored grade
  flags were not used, because several are wrong in production (MLB spread sign, NHL blank team
  names, NBA wrong-day box scores).
- Hit = the projection's side of the stored line matches the actual's side. Pushes, did-not-play and
  rows with no line are excluded from hit rates. Rows are deduplicated to the latest per player or
  game and date. Intervals are Wilson 95%.
- Breakeven is 52.4% at -110. Where a real price is stored, the true breakeven is higher (see X-3).
- Queries and outputs: `.factory/projection-analysis/{nba,nfl,nhl,mlb,wnba}/` in the audit worktree
  (not committed).

## Scoreboard

MAE is mean absolute error. "Market" is the error of the betting line on the same rows.

### NBA (2026-27, through 11-12)

| Market | Graded (with line) | Bias (actual − projected) | MAE vs market | Hit at playing edge | Verdict |
|---|---|---|---|---|---|
| Points | 2,599 (1,512) | −0.54 | 5.33 vs 4.99 | 49.0%, n=910 [45.8, 52.3] | Loses |
| PRA | 1,509 (1,008) | −0.57 | 6.89 vs 6.54 | 51.3%, n=600 [47.3, 55.3] | Loses |
| Rebounds | 2,599 (1,309) | −0.19 | 2.03 vs 1.96 | 53.8% at edge ≥ 0.5, n=701; about 56% at ≥ 1, n≈303 | About even |
| Assists | 2,599 (1,008) | −0.11 | 1.79 vs 1.74 | 54.2%, n=518 [49.9, 58.5] | About even |
| Threes | 2,587 (994) | −0.07 | 1.23 vs 1.23 | 54.9%, n=395 [50.0, 59.8] | About even |
| Steals, blocks, free throws | 2,598 each, no lines | about 0 | worse than a last-10 average | none | Cannot be bet |
| Game totals | 174 | +4.66 | 15.91 vs 13.85 | 45.9%, n=122, 93% unders | Loses |
| Spread | 174 | −0.02 | 11.44 vs 11.03 | 52.4% ATS, n=105 [42.9, 61.7] | Loses on error |
| Win probability | 172 | n/a | Brier 0.201 vs 0.180 | moneyline ROI −12%, n=145 | Loses |

### NFL (2026, weeks 1 to 10)

| Market | Graded | Bias | MAE vs market | Calls | Verdict |
|---|---|---|---|---|---|
| QB passing yards 2026 | 198 | +1.7 | 56.2 vs 48.8 | 47.8% (22/46), ROI −9.9% | Loses |
| QB passing yards 2025 | 407 | −13.3 | 66.3 vs 54.8 | 47.6% (107/225), ROI −10.6% | Loses |
| QB over/under classifier | 110 | leans under | Brier 0.268 vs coin flip 0.250 | its own calls 45% (18/40), ROI −15% | Worse than a coin flip |
| Anytime TD | 1,726 (1,354 priced) | raw 0.173 vs 0.273 observed | Brier 0.1745 vs 0.1702 | "No TD" 66.0% vs fair 67.3% | Loses |
| Kicker field goals | 275 | +0.15 | 0.960 vs league constant 0.932 | no line stored | No skill |
| Spread | 137 | −2.68 | 10.09 vs 9.45 | 49.0% (25/51) | Loses |
| Win probability | 136 | 0.588 vs 0.493 observed | Brier 0.235 vs 0.216 | home backing 40% vs 43% implied | Loses |
| Totals | 137 | +0.60 | 11.19 vs 10.55 | 42.9% (27/63) | Loses |
| Receiving yards | 21 | −1.8 | 15.2 vs 21.5 | none | Too little data |

### NHL (2026-27, through 11-12)

| Market | Graded (with line) | Bias | MAE vs market | Hit at playing edge | Verdict |
|---|---|---|---|---|---|
| Player shots on goal | 1,676 (597) | −0.43 | 1.76 vs 1.29 | 46.9%, n=258 [40.9, 53.0] | Loses |
| Game totals (graded here for the first time) | 297 (256) | +0.18 | 1.82 vs 1.73 | 44.0%, n=191 [37.1, 51.1], ROI −19% | Loses |
| Goalie saves | 0 this season; never a row with a line | n/a | old system 5.90 vs a constant 5.64 | none | No record |
| Team shots | no projections written | | | | Not projected |

### MLB (2026 season, look back)

| Market | Graded (with line) | Bias | MAE vs market | Hit | Verdict |
|---|---|---|---|---|---|
| Pitcher strikeouts | 3,201 (1,346) | +0.81 (too low) | 2.37 vs 1.79 | classifier pick 46.4%, n=980 | Loses |
| Game totals | 2,276 (1,451) | −0.53 | 3.63 vs 3.34 | 51.2%, n=693 | Loses |
| Moneyline | 1,069 | n/a | Brier 0.2426 vs 0.2319 | 47.7%, n=591, ROI −2.5% | Loses |
| Run line (regraded) | 1,300 | n/a | n/a | 57.5%, but 94% are +1.5 at the base rate | No skill |
| Hits and home run boards | 1,390 / 757 | n/a | no line | equal to the base rate | Not a model |

### WNBA (2026 season, look back; no prop prices stored)

| Market | Graded (with line) | Bias | MAE vs market | Hit at playing edge | Verdict |
|---|---|---|---|---|---|
| Points | 5,455 (1,276) | +0.36 | 5.13 vs 3.91 | 49.1%, n=910 | Loses |
| Rebounds | 5,455 (980) | 0.00 | 2.15 vs 1.73 | 52.2%, n=653 | Loses on error |
| Assists | 5,455 (674) | −0.03 | 1.82 vs 1.49 | 53.6%, n=416 | Loses on error |
| Threes | 2,090 (395) | +0.03 | 1.00 vs 0.875 | 58.6%, n=191; unders 68.8% | Unpriced, cannot verify |
| PRA | 1,379 (360) | −0.01 | 6.69 vs 5.01 | 47.9%, n=263 | Loses |
| Totals | 320 (308) | +1.9 | 15.6 vs 13.3 | 51.6%, n=250 | Loses |
| Spread | 309 | +0.33 | 10.6 vs 9.7 | 49.7%, n=308 | Loses |

## Issues

Size: S is under a day, M a few days, L more. Status is against PR #177.

### Cross-cutting

| ID | Problem | Remedy | Size | Status |
|---|---|---|---|---|
| X-1 | Projections are published as bets with no requirement that the market has a winning graded record. | Record gate withholds losing markets (in #177). Turn on prove-in mode (`AUTO_PICK_REQUIRE_PROVEN_RECORD`) so a market with no record cannot publish. Until then, picks are being published from markets that measurably lose. | S | Partly: losing markets withheld; prove-in is opt-in |
| X-2 | Models are gated against a naive baseline or Elo, never against the line they are meant to beat. | Every trainer's promote gate compares holdout error with the stored market line on the same rows. NBA spread has this in #177; add it for NBA props, NFL QB, NHL and MLB. | M | Partly |
| X-3 | Hit rates are judged against 52.4%, but stored pick-side prices are worse than -110 (NBA medians: points −115, rebounds −125, assists −128, threes −138). | Grade every call at its stored price. Store both sides' prices for every market (NBA props only since 11-13; WNBA props, NHL shots, MLB run line and NFL "No TD" have none). | S to M | Not addressed |
| X-4 | No closing lines are stored, so closing-line value cannot be measured, and game-line tables hold only the latest line, not the line at projection time. | Snapshot the line when the projection is written and again at game start, in their own columns. | M | Not addressed |
| X-5 | The inputs behind a projection are not stored, so a bad projection cannot be traced after the stats tables are overwritten. | Store the feature snapshot on the row (several tables already have a `factors` or `features_used` column that is empty or partial). | M | Not addressed |
| X-6 | Projection history was rewritten after game start. | Frozen at game start in every sport. | n/a | Fixed |
| X-7 | Grading used different rules on different screens and counted no-plays as losses. | One row-level grading definition. | n/a | Fixed |
| X-8 | Retrained models did not reach serving, were not compared with the live model and could not be rolled back; rows carried no model version. | Reload on change, strictly-better gate with archive, `model_version` on 19 tables. | n/a | Fixed |
| X-9 | Stats that never reach a line are projected and shown (NBA steals, blocks, free throws; NHL skaters with no line; MLB boards). | Show and grade only rows with a line, or label the rest as estimates. | S | Not addressed |
| X-10 | A weekly pipeline can fail silently for weeks (NFL QB weeks 2 and 3 were never projected; NHL goalie actuals have no rows this season). | Add a per-sport "board is thin" check to the daily model review: expected row counts per market per slate. | S | Partly: the review exists, the row-count check does not |

### NBA

| ID | Problem and evidence | Cause | Remedy and measure | Size | Status |
|---|---|---|---|---|---|
| NBA-1 | Box scores mis-dated and duplicated. 12,497 of 20,670 last-season rows and 826 of 3,756 this season sit one day late; 1,161 duplicate pairs from 11-02 to 11-09. 548 of 1,685 stored points grades this season (33%) are against the wrong game or value. | `update_recent_games.py` filed by UTC date before #173; the fix applies only going forward, and the 7-day re-run re-filed rows without deleting the old ones. `store_actuals.py:208-216` and the feature builders read the shifted rows. | One-off repair: re-date each row to the real game date, delete duplicates, re-run actuals for the season, add a uniqueness guard, then retrain points, rebounds and assists. Check whether the repair action from #174 was ever run. Measure: 0 duplicate pairs, 0% mismatch against the schedule. | M | Not addressed |
| NBA-2 | Totals adjustments drag the number down and carry no signal. Mean components: rest −1.98, form −1.64, injury −1.38. The base with no adjustments is unbiased with MAE 15.05 against 15.91 published. No component predicts actual minus market. | `totals_projector.py:690-704` adds the terms on top of a baseline whose bias correction was fitted without them. | Drop rest, injury and form from the projected total; keep them as display factors. Keep calls off until 30 new-version picks reach breakeven. Measure: bias within ±1 over 100 games, MAE gap to market under 0.5. | S | Partly: #177 corrects the published bias in aggregate (replayed bias +1.16) but the error stays above market |
| NBA-3 | Rest penalty applied for back-to-backs that did not happen: 84 of 183 rows. | `totals_projector.py:376-417` reads the mis-dated rows from NBA-1. | Delete the term, or compute rest from the game-lines schedule. | S | Not addressed |
| NBA-4 | Points and PRA props are worse than the line (5.33 vs 4.99). The edge is 90% noise (slope 0.10). Calls 4 or more points from the line have MAE 7.00 against 5.27. Mid-rotation players are leaned over and hit 45 to 48%. | XGBoost trained on features corrupted by NBA-1; no market gate. | Keep out of auto picks (gate does this). Shrink to the line when more than 3 away. After NBA-1, retrain with a beats-the-line gate. Measure: lined-row MAE no worse than the line over 1,000 rows. | M to L | Partly |
| NBA-5 | Threes, steals, blocks and free throws are worse than a last-10-game average (threes 0.999 vs 0.928). | Static S3 files with no training code. | Serve the last-10 average until a trained model beats it; add these stats to the weekly retrain. | S | Not addressed |
| NBA-6 | Spread model worse than market (11.44 vs 11.03); the edge has no slope; best blend weight on the model is about 0.1. | Gated only against Elo. | Publish market margin plus 0.1 × model; withhold spread calls. | S | Partly: training gate now compares with market; serving unchanged |
| NBA-7 | Win probability miscalibrated: predicted 0.816, observed 0.719 at the extremes; moneyline ROI −12%. | Fixed logistic on the model margin, scale 7.0 (`etl/_spread_model.py:86`). | Derive win probability from the market spread (scale about 6.5) with the model as a small nudge. Measure: Brier within 0.005 of market. | S | Not addressed |
| NBA-8 | The totals record gate scores past model versions for up to 60 days after a fix. | `current_pick_record` uses a date window. | Scope the record by `model_version` (now stored). | S | Not addressed |
| NBA-9 | Steals and blocks lines are never fetched. | `PROP_MARKETS` in `_fanduel_lines.py:248` omits them. | Add the two markets. | S | Not addressed |
| NBA-10 | 24% of real-game prop rows have no box score (14% by the week of 11-09); 28 early-season games missing from totals actuals. | Players projected who do not play; grading only looked back one day. | Lookback grading is in #177; tighten the active-player filter. | S | Partly |
| NBA-11 | Prop calls before 11-10 showed the wrong side on 21 to 54% of rows. | Fixed in #170. | Any record built on the stored side before 11-11 must be recomputed. | S | Fixed on main |

### NFL

| ID | Problem and evidence | Cause | Remedy and measure | Size | Status |
|---|---|---|---|---|---|
| NFL-1 | A classifier with live Brier 0.268 creates 50 of 56 QB calls; they hit 45%, ROI −15%. | `qb_betting.py:179-183` makes a call on the classifier alone; the loader falls back to the repo model, which passes the holdout gate. | Remove the classifier-only call path. Gate any future use on live Brier under 0.25 over 100 graded rows. | S | Fixed in #177 |
| NFL-2 | With ML on in production, the published QB number is the line minus about 4 yards: never a bet, slightly worse than the line (56.4 vs 55.1). | `published_qb_yards` publishes the residual model as is. | After two clean weeks, either switch the flag off so the soft anchor publishes, or remove the global under-shade. Measure: MAE no worse than the line and side hit at least 52.4% over 120 clean rows. | S to decide, M to validate | Not addressed |
| NFL-3 | 204 of 275 QB rows in 2026 were rewritten after kickoff, many graded against next week's line; 23 of 56 calls point the opposite way to the stored yards. | No kickoff freeze before #170. | None for new rows. Re-measure from week 10. Follow-up: clear the call when `qb_dynamic` changes the yards; lift the `limit(32)` that drops 1 to 4 QBs a week. | S | Fixed on main; follow-ups not addressed |
| NFL-4 | Anytime TD raw probability is 10 points low (QB 0.031 vs 0.172 observed) and adds nothing beyond the price; 427 "no TD" calls, most with no price. | Position priors in `anytime_td_features.py:41-75`; the market anchor keeps about 70% of a biased model. | Stop anytime-TD calls, publish the market fair probability, recalibrate per position walk-forward. Measure: published Brier no worse than market on 600 priced rows. | S to stop, M to recalibrate | Not addressed |
| NFL-5 | Every graded anytime-TD price was written after the game. | Name-only match against upcoming events before #170. | None for new rows. Re-measure from week 10. | S | Fixed on main |
| NFL-6 | Kicker projection has no signal (correlation 0.02 to 0.05); 5,808 rows written in the off-season. | Near-constant baseline blended with a model trained on a static CSV. | Do not surface until attempts use game context (implied team total, spread, dome and wind). Gate off-season writes. | M | Not addressed |
| NFL-7 | Spread has a home bias (+2.65 projected, −0.02 actual); win probability overconfident for home teams. | Basketball defaults in the shared Elo config; home advantage 2.5. | Project margin as market plus a small fitted weight on Elo minus market. Never call against the spread from Elo alone. | S | Not addressed |
| NFL-8 | Totals: all adjustment columns are 0 on 137 of 137 rows; larger edges do worse (29% at edge 5 to 8). | Plain points-per-game average with no shrinkage. | Stop totals calls, or shrink toward the market and fit the weight. | S | Not addressed |
| NFL-9 | Receiving yards cannot be judged yet; the week-10 board is 60 overs to 3 unders. | Rebuilt on 11-10. | Grade weeks 10 and 11, then re-centre if the bias against the line stays above 3 yards. | S | Not addressed |
| NFL-10 | QB `model_version` is 20 characters and truncates the version string. | Column width. | Widen the column. | S | Not addressed |
| NFL-11 | Weekly QB retrain cannot be validated against the live model. | The gate compares different holdouts. | Stays manual. A sound weekly rule: ship a refit when the promote check passes and the data window moved. | M | Deliberately left manual |

### NHL

| ID | Problem and evidence | Cause | Remedy and measure | Size | Status |
|---|---|---|---|---|---|
| NHL-1 | Every model input is stale. Team stats match only preseason games; game history ends 2025-11-22; 97 skater rows are 1 to 9 game samples from October 2025; goalie "season" stats are career totals; `last_game_date` is never written. | `collect_historical_data.py:408` filters on a game state that only preseason rows have; `:1181` caps at each team's first 20 games; `nhl_api_client.py:216-218` returns 50 of 940 skaters; `:323` aggregates every season. | Filter team stats to the current regular season; remove the 20-game cap; add `limit=-1`; compute goalie stats per season and write `last_game_date`; project only skaters with 5 or more games this season. Measure: team games played equals the standings daily; shots MAE on lined rows at or below the line within 300 rows. | M | Not addressed |
| NHL-2 | Shots model has no skill (correlation 0.085 against the line's 0.32); 222 of 258 plays are overs; the plain season average beats the adjusted number. | Ice-time multiplier double counts; home ×1.05 with no away offset (`player_shots_model.py:64-129`). | After NHL-1, use shots per game shrunk to a prior; drop the ice-time and home multipliers; no labels or picks until 300 lined rows clear the line. | S | Not addressed |
| NHL-3 | Totals have no skill (44.0%, ROI −19%) and the auto-pick source is registered. | Preseason inputs, a net +2.5% home and away tilt, thresholds of 0.25 and 0.5 goals. | Withhold now (the record gate will, once #177 deploys and grading works). Rebuild as per-team goals shrunk to the league mean, keyed by team id. | M | Partly |
| NHL-4 | Goalie saves has no record: no rows this season and never a stored line. On old rows the projected goalie did not play in 49% of games. Auto picks start 2026-11-14. | NHL-1 inputs; starters were never confirmed before #176. | Run in shadow until 150 graded confirmed-starter rows with a line clear the line. Prove-in mode (X-1) does this when switched on. | S | Opt-in in #177 |
| NHL-5 | "New York" and "Utah" each match two teams by name, so the Rangers and Islanders share stats. | Team stats looked up by place name in three models. | Look up by `team_id`. | S | Partly: actuals fixed, model lookups not |
| NHL-6 | 43% of projected skaters have no actual (departed and retired players); only 21 to 27% of rows carry a line. | Top 5 per team by a stale table; lines fetched only at 05:00 ET; exact-name matching. | Project from the game roster; refresh shots and totals lines in the 16:45 job. | M | Not addressed |
| NHL-7 | Preseason games sit in the graded record (208 shots rows, 65 totals rows). | No game-type filter. | Skip game types other than regular season and playoffs. | S | Not addressed |
| NHL-8 | Shadow ML has never produced a row. | Flags off, no trained artifacts. | Train only on data collected after NHL-1. | S | Partly |

### MLB (before the 2027 season)

| ID | Problem and evidence | Remedy | Size | Status |
|---|---|---|---|---|
| MLB-1 | Strikeouts projected 0.8 low in both seasons and every classifier version; the classifier pick hits 46.4% (n=980). | One multiplicative calibration on 2025 and 2026 graded rows, then a time-split retrain. Store `matchup_factor` on the row so training matches serving. | M | Partly: retrain gating only |
| MLB-2 | Totals tilt over: model 9.46 runs against a line of 8.36; 646 over calls to 69 under. | Fit an intercept and shrink toward the market. | S | Not addressed |
| MLB-3 | Win probability worse than market; the largest disagreements win 28.4%, ROI −17%. | Blend toward the no-vig market; drop picks more than 10 points from it. | S | Not addressed |
| MLB-4 | Run-line picks are "take +1.5" at the base rate, with no price stored. | Store run-line prices; drop the picks until priced. Run the regrade script after deploy. | S | Partly: sign fixed |
| MLB-5 | Strikeout line coverage fell from 82% to about 40%; no strikeout actuals before 2026-05-24 or in the postseason. | Fix the line fetch before opening day. | S | Not addressed |
| MLB-6 | Hits and home run boards are not models. | Label as trends, or replace. | S | Partly: out of the headline number |

### WNBA (before the 2027 season)

| ID | Problem and evidence | Remedy | Size | Status |
|---|---|---|---|---|
| WNBA-1 | Props lose to the line in every stat, worst on players who have lines (5.13 against 4.18 on all rows). | Check bias by minutes and usage; port the NBA trainer fixes (in #177) and add a beats-the-line gate. | M | Partly |
| WNBA-2 | No prop prices stored, so the threes-under result (68.8%) cannot be confirmed. | Store the price of the side. | S | Not addressed |
| WNBA-3 | Totals shadow ML is worse than the heuristic (16.5 vs 15.8). | Keep it off. | n/a | No action |
| WNBA-4 | 24% of projected prop rows have no actual. | Tighten the active-player and injury filter. | S | Not addressed |

## Recommended order

1. **Stop publishing from unproven markets.** Decide on prove-in mode (X-1). This is a switch, not a build.
2. **Repair NBA box-score history** (NBA-1), then drop the NBA totals adjustments (NBA-2, NBA-3) and retrain props. This is the largest single source of error in the highest-volume sport.
3. **Fix NHL inputs** (NHL-1, NHL-5, NHL-7). Nothing else in NHL is worth doing first.
4. **Anchor game markets to the line** (NBA-6, NBA-7, NFL-7, NFL-8, MLB-2, MLB-3): publish market plus a small fitted weight on the model. One shared helper covers all of them.
5. **Stop the calls that measurably lose** while the models are rebuilt: NFL anytime TD (NFL-4), NFL totals (NFL-8), kickers (NFL-6).
6. **Store what makes measurement possible** (X-3, X-4, X-5): prices on both sides, line snapshots, input snapshots.
7. **Re-measure NFL from week 10** in two to three weeks, then decide NFL-2 and NFL-9.
8. **Add the beats-the-line gate to every trainer** (X-2), then rebuild the remaining models behind it.
9. MLB and WNBA items before their seasons return.

## Corrections to earlier findings

- The 2026-11-07 conclusion that NBA props over-project rebuilding teams does not hold once games are dated correctly.
- The NBA scorecard blamed form and injury for the totals drag; the largest piece is rest, most of it false back-to-backs.
- The daily NBA scorecard reads the contaminated prop grades, so its prop hit rates are off until NBA-1 is repaired.
- `NFL_QB_ML_ENABLED` is on in production. The QB classifier making calls is the repo model, not the S3 one.
- The NHL issue YetAI-j6t is real but the cause is duplicate place names, not a full-name mismatch.
