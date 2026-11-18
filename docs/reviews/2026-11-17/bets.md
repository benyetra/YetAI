# YetAI Bets (signature auto picks) and the record gate: findings, 2026-11-17

Scope: `backend/app/services/auto_pick/*`, `tasks/auto_pick.py`, `services/etl/nba/_fanduel_lines.py`,
`services/odds_math.py`, `services/yetai_grading.py` + `espn_results.py`, `services/model_review_service.py`,
`api/v1/predictions.py`, `frontend/src/lib/propDiscoveryConfigs.ts`. Code at 5b662edf.

## What actually got picked (from the four daily reviews)

All 13 settled straight bets fall inside "last 7d" in every report, so these are cumulative:

| Review | Settled straight | New since previous day |
|---|---|---|
| 11-14 | 7: 5-2, +2.42u (NBA 3-2, WNBA 2-0, ML 1-0, props 1-1 at 0.00u, spread 3-1) | (first report) |
| 11-15 | 9: 5-4, +0.42u | 2 NBA props, both lost (-2.00u) |
| 11-16 | 11: 5-6, -1.58u | 2 NBA props, both lost |
| 11-17 | 13: 5-8, -3.58u | 2 NBA props, both lost |

- Since 11-14 the auto picks have been 2 NBA props a day and nothing else: **0-6 since 11-14**. The spread, ML
  and WNBA rows have not changed since the first report (see F5: most of them are probably not auto picks).
- Gate lines for bet records (`bets n units`): threes 2 bets -2.00u, points 1 bet +1.00u (same on 11-15, 11-16
  and 11-17). So the first props were 1 points win and 2 threes losses, from the 11-13/11-14 slates, before
  the gate withheld those keys.
- `bets:` model versions (created in 30 days): 11-15 `xgb-202611141637` 1 (the assists model) and `sum-pra-v1` 1;
  11-16 2 and 2; 11-17 2 and 4. The six losses since 11-14 fit **about 4 PRA plus 2 assists**. Rebounds was
  never picked. Settle this with Q1 at the end.
- 8 props at 1-7 = -6.00u: seven losses at -1u plus one win at exactly +1.00u, so the stored odds on the
  winning points bet were +100 or -100 (`record_gate.stake_units`, record_gate.py:165).

---

## F1. PRA props publish with no record, and they are now most of the picks (gate hole + selection)

**What is wrong.** NBA PRA (points + rebounds + assists) is a registered auto-pick market that the record
gate never measures. The gate withholds points for losing, yet PRA, which is the points projection plus two
others, publishes freely, and the scorer ranks it at the top of the board.

**Evidence.**
- `sources/player_prop_source.py:28` registers `(PRAProjections, "pra", ...)`. `record_gate._NBA_PROP_STATS`
  (record_gate.py:249-255) has points, threes, steals, assists and rebounds, **no pra**, so no projection
  record exists for it. The comment at record_gate.py:461 says so ("NBA moneyline / pra props ... bet record
  only"). `DEFAULT_PROVE_IN_KEYS` (record_gate.py:63) does not list it. `drop_reason` (record_gate.py:147)
  returns None: n_eff = bet_n < 30, so it can never be withheld, and prove-in is off.
- The PRA projection is a plain sum of the points, rebounds and assists projections
  (`etl/nba/generate_pra_predictions.py:191-215`, `model_version "sum-pra-v1"`). Points is withheld as losing
  (11-17: shrunk ROI -3.5%, 474/964) and its edge is about 90% noise (register NBA-4).
- Scoring, reproduced with the production scorer (no DB): a PRA over 6 points above the line scores **82.5**,
  the same at -115, at +120 and (81.8) at -160. Clearing the 65 threshold needs only 3.4 PRA points
  (`PROP_EDGE_BY_STAT["pra"] = 6.0`, sub_scores.py:28). An assists over 1 point above the line at -125 scores
  62.5 and a rebounds over 1 point above scores 58.5, so a big PRA gap beats almost every other prop.
- Data: bets `sum-pra-v1: 4` of 6 versioned bets (11-17 review). The review has no PRA accuracy line at all.
  The only PRA read is fair-price secondary `player_points_rebounds_assists: n=123, hit 51.2%, ROI -5.6%`
  (11-17).

**Mechanism.** The largest PRA gaps are mostly the largest points-projection errors, summed with the rebounds
and assists errors. Withholding points therefore achieves nothing: the same error comes back through PRA,
unmeasured.

**Confidence.** CONFIRMED (code reproduced; the bets' model_version counts match).
**Register.** New. X-1 covers "markets with no record" only in general terms.
**Fix (S).** Add `"pra_ou": ("pra", "actual_pra", "projected_pra")` to the gate's NBA loader (first check the
part name `_nba_season_window_rows` emits for PRA, and add the PRA rows there if they are missing), and add
`NBA/player_prop/pra` to `DEFAULT_PROVE_IN_KEYS` until it has a record. Quicker still: drop the PRA spec from
`_NBA_STAT_SPECS` until points is admitted.

## F2. The selector picks the biggest projection-to-line gaps, ignores price, and never asks if the bet is +EV (selection logic)

**What is wrong.** The score is about 40% "how far the projection is from the line", capped. Nothing in it
turns the gap into a win probability, shrinks it, or compares it with the price. With a model that has no
edge, this picks the model's biggest errors, at whatever price the book offers.

**Evidence.**
- `sub_scores.edge_sub_score` (sub_scores.py:84-100) is `(proj - line) / normalizer`, capped at 100. The
  weights (scoring_context.py:8-13) give edge 0.40. The other terms are almost constant for NBA props:
  historical is about 50; freshness is always 100 because `generated_at` is None (F6); line movement is 50
  (no snapshot data is fed in); model_conf is about 50.
- Price: `odds_sanity_sub_score` (sub_scores.py:156-162) is 100 for any price from -150 to +150. The hard gate
  only enforces -300 to +400 (selector.py:27-28). A -150 over (breakeven 60%) scores the same as a +120 over
  (breakeven 45.5%). There is no minimum price, no EV check and no both-sides (no-vig) check.
- The price used is a line-shopped best quote (`_basketball.prop_rows` 239-243 takes `best_book/line/price`).
  `odds_math.best_quote` (odds_math.py:148-185) ranks books by EV at the consensus fair probability. That part
  is sound. But it returns the best quote **even when that EV is negative**, and the `fair`/`ev` it computes
  is thrown away (`_fanduel_lines.py:396-398` stores only book, line and price). So a stale line at the best
  book is not the problem. The problem is that nothing requires the bet to beat the consensus.
- No shrinkage anywhere: no shrink-to-line in the points, assists, rebounds or PRA generators (grep: none),
  and none in the selector. The register's own fix for NBA-4 ("shrink to the line when more than 3 away") is
  not done.
- Data showing that big gaps do not win (11-17 props audit): points `|edge|>=3: 50.0%` (336), assists
  `|edge|>=2: 45.2%` (42). 30-day hit rates at the stored side: assists 50.3%, rebounds 49.1%, points 47.9%,
  against true breakevens of 56.1%, 55.6% and 53.5% at the stored median prices. CLV is negative on every NBA
  prop market: prob CLV -1.7 to -2.5pt, with only 8-19% of calls beating the close (11-17 CLV section).

**Mechanism.** If the edge is mostly noise (register NBA-4: slope 0.10, calls 4+ from the line have MAE 7.00
against 5.27), ranking by its size selects the rows where the noise is largest. The pick then pays the median
-125 to -140 vig on a coin flip. Expected ROI for a neutral model at -125 is about -10% a bet, before any
extra adverse selection.

**Confidence.** CONFIRMED (code plus the audit and CLV numbers).
**Register.** NBA-4 is listed and still open. The selector side of it is new.
**Fix (M).** Score props by expected value, not distance:
p = P(side | line, mean = line + k·(proj - line), sd = MARKET_SD), with k fitted per stat (points about 0.1);
EV = p·decimal(price) - 1. Require EV > 0 **and** best_quote's consensus EV ≥ 0, which means storing `fair`
and `ev` next to `best_price`. Replace the capped edge term with EV. Smallest interim step (S): make
`hard_gate_reason` drop candidates whose stored consensus EV is below 0, and cap `|proj - line|` at one
normalizer before scoring.

## F3. The gate values about 80% of graded calls at -110 when the real price is -125 to -140, and its shrinkage hides big samples (gate hole)

**What is wrong.** The record gate asks "would these calls have made money?" mostly at a price nobody was
offered, with a prior capped at 60 effective calls and a -2% dead band. Markets that lose at real prices stay
open. Assists and rebounds are the live examples.

**Exactly what the gate computes** (record_gate.py:172-202, defaults):
- Rows: NBA prop rows with a FanDuel line over [today-90d, today-1] (Eastern), **all model versions**, graded
  on the **stored** side (`fanduel_over_under`). Only rows whose signed edge on that stored side is at least
  `fill_floor_edge(stat)` are kept (record_gate.py:302-334). Floors, computed: points 1.25, rebounds 0.78,
  assists 0.625, threes 0.375, steals 0.25 (pra would be 1.875).
- Units: `ou_call_graded_record` with `price_field="fanduel_price"` (accuracy_shared.py:495-498). A row with
  no stored price counts at **-110**. The price column only exists from 2026-11-13, so most rows in the
  window have none: priced 252/1312 assists, 323/1681 rebounds, 267/1295 threes in the 30-day view (11-17).
- `scale = min(1, 60 / proj_n)`, `n_eff = proj_n·scale + bet_n` (so at most 60 + bets),
  `shrunk = (units·scale + bet_units) / (n_eff + 20)`, withheld if `n_eff ≥ 30 and shrunk < -0.02`.
  With no bets, shrunk = 0.75 × raw ROI, so a market is withheld only when its raw ROI is below **-2.67%**,
  whether it has 60 or 1,700 graded calls.

**Reproduced with the 11-17 numbers.** threes: `combine(bet_n=2, bet_units=-2, proj_n=410, proj_hits=219,
proj_units=-6.5)` gives n_eff 62.0 and shrunk -3.60% (report: 62.0, -3.6%). points: `proj_n=964, hits=474,
units=-61.6, bets 1/+1` gives 61.0 and -3.50% (report: 61.0, -3.5%). Working back: threes hit 53.4% in the
gate subset, which is +8.1u at -110, but -6.5u once the 20% of rows with real (median -140) prices are counted.
Points is -59.1u at -110 and -61.6u at mixed prices.

**Why assists and rebounds pass.** The report prints only withheld keys, so their figures are not in the
evidence. The arithmetic shows how they pass anyway. Take a qualifying subset that hits 55% (the audit has
assists 54.1% at |edge|≥0.5 and 56.3% at ≥1.0; rebounds 53.9% and 56.7%). Per-bet EV is +5.0% at -110 and
-2.0% at -128, so a mix that is 80% unpriced shows **+3.6% raw (+2.7% shrunk): open**, while the real-price
ROI is -2.0%. At 53.9% (the rebounds |edge|≥0.5 bucket) the mix shows +1.7% (open), while at -125 it is -3.0%
(shrunk -2.2%: **withheld**). The -110 default alone flips the decision.

**Other gate issues found.**
- Not scoped by `model_version`. Assists `xgb-202611141637` has 621 rows against 4,594 `None` rows in 30 days.
  Rebounds changed model again on 11-16. The gate judges the current model mostly by its predecessors.
  This is register NBA-8, which applies to props as well as totals.
- The gate grades the FanDuel line and price, but the picks are placed at `best_line` / `best_price`
  (`_basketball.py:239-243`), so the gate and the bets are two different populations.
- NBA-11 (wrong stored sides before 11-11) is **not** a material gate hole, which goes against the brief's
  suspicion. A wrong stored side gives a negative signed edge on that side, so `_prop_qualifies` drops the
  row instead of mis-grading it. It shrinks the early sample; it does not bias it toward "open".

**Confidence.** CONFIRMED for the computation and the threes/points reproduction. HYPOTHESIS for the exact
assists, rebounds and PRA gate figures. To settle it, run the gate's own read-only CLI against a read replica:
`cd backend && DATABASE_URL=<replica> PYTHONPATH=. python -m app.services.auto_pick gate --now 2026-11-17T16:00:00`
and read the `proj_units` / `n_eff` / `ROI` columns for the assists, rebounds and pra rows.
**Register.** X-1 is "partly fixed". This price hole and the n_eff cap are new.
**Fix (S).** In `_nba_props`, grade only rows with a stored price, or value an unpriced row at the stat's
median stored price instead of -110. Let the prior grow with evidence, e.g. `PRIOR_MAX_PICKS` 300 and
`MIN_ROI` 0 once n_eff ≥ 300. Filter rows to the candidate's current `model_version` once each version has
30 or more graded rows. Also print every key's gate row in the daily review, not only the withheld ones
(`model_review_service._gate_section`, :589).

## F4. With prove-in off, markets with zero record publish (gate hole, bd YetAI-e7g)

**What can publish today.** Registered sources (`tasks/auto_pick.py:47-71`): NBA props (points, steals,
assists, rebounds, threes, pra), NBA spread, total and moneyline; MLB strikeouts and moneyline; NHL goalie
saves and totals; NFL passing yards, receiving yards, spread and total; WNBA props, spread and totals.
`AUTO_PICK_REQUIRE_PROVEN_RECORD` defaults to false (record_gate.py:83-87) and the 11-17 review shows no sign
it was changed. Status on 11-17:
- **Open with a record:** NBA assists, NBA rebounds (see F3).
- **Open with no record at all:** NBA PRA (F1), NBA moneyline (bet record only, 1 bet), NFL receiving yards
  (`0/0 calls`, n_eff 0), and WNBA and MLB (off-season, so no candidate rows; their keys would also open with
  no record).
- **Withheld, losing:** NBA points and threes; NFL spread, total and passing yards.
- **Withheld, prove-in default:** every NHL key, and NBA steals (13/21, n_eff about 21 < 30). NBA blocks has
  no source.
- **NBA spread and totals:** effectively closed by their own version gate ("0 graded picks of this version,
  30 needed"): the source sees `recommendation = NO_PLAY`.

So on an NBA night the candidates are assists, rebounds and PRA. `max_per_market = 2` (selector.py:35) is the
reason every day has exactly 2 NBA props and no third pick.

**Confidence.** CONFIRMED (code; the NFL receiving and steals numbers are from the 11-17 accuracy section).
**Register.** X-1 / YetAI-e7g, listed and still open.
**Fix (S).** Set `AUTO_PICK_REQUIRE_PROVEN_RECORD=true` on celery-worker and restart it. That withholds PRA,
NBA moneyline and NFL receiving until each has 30 effective calls. It does **not** fix F3: assists and
rebounds would still pass.

## F5. The "YetAI Bets record" in the review mixes in legacy re-graded rows, and bets cannot be audited against their projection (plumbing/audit)

**What is wrong.**
1. `_bets_section` (model_review_service.py:483-509) does not filter `source = AUTO` and windows on
   `settled_at`. PR #175 (merged 2026-11-13) re-graded "old rows stuck in expired / pending_manual_review"
   (PR body), which gives them a settled_at around 11-13 and puts them in "last 7d". That is the most likely
   source of the **WNBA 2-0 (+1.83u)** and of the **2 voids "vs Phoenix Mercury: Could not parse pick"**.
   The WNBA season is over and WNBA jobs are off, so these are in-season legacy rows (the title "vs Phoenix
   Mercury" and the unparseable free-text selection fit admin-entered manual picks). The 4 spreads (3-1) and
   the ML win, unchanged since the first report, are probably the same kind of row. If so, the auto-pick
   record proper is about **1-7 props, -6u**.
2. `_versions_section` (:775-783) counts every yetai_bets row *created* in 30 days, of any status and source:
   `None: 133` is mostly rows that were never shown (rejected / expired pending_approval / manual), not
   published bets. So the numbers in the brief's question are not a count of bets.
3. "0 of 4 compared; 6 bets without projection_ref; 2 unmatched": the 6 without a ref are pre-#175 rows (auto
   rows get `projection_ref` from `candidate.projection_ref`, `_basketball.py:249-251`, stored at
   orchestrator.py:829). The 2 unmatched are probably PRA bets: the review's `load_rows` has no PRA loader, so
   `_lookup` cannot find them. Also, the projection row a bet points to is **updated in place** by the 12:00
   and 17:00 refreshes (`generate_pra_predictions.py:217-221`, `apply_fanduel_to_projection` rewrites line,
   side and price). An 11:00 pick is therefore compared against a later projection. The pick-time values do
   survive, in `prediction_factors.market_line / our_projection / projection_metadata`.
4. The gate's bet loader *does* filter AUTO (record_gate.py:213), so the gate and the review disagree on what
   "the bet record" is.

**Confidence.** CODE-ONLY for 1-3; HYPOTHESIS for which rows they are. Settle it with Q1 and Q2 below.
**Register.** New.
**Fix (S).** Filter `YetAIBet.source == BetSource.AUTO` in `_bets_section` and `_disagreements_section`, and
report manual rows separately. Window on game date, not `settled_at`. Count versions only for shown statuses.
Compare each bet to its own `prediction_factors` snapshot plus the final actual, not to the mutated row. Add
PRA to the review loaders.

## F6. Prop picks are not checked for freshness, and the 11:00 run publishes overnight prices (plumbing)

**What is wrong.** NBA prop candidates always score freshness 100, and nothing re-checks that the line and
price still exist at publish time.

**Evidence.** `player_prop_source._NBA_STAT_SPECS` passes `None` as the timestamp attribute
(player_prop_source.py:23-29), so `generated_at = None` (`_basketball.py:266`) and `freshness_sub_score` skips
the age check (sub_scores.py:121-137). The rows do carry `projected_at` (`_fanduel_lines.py:364`). Schedule:
the NBA pipeline runs at 03:30 ET and the pregame refresh at 12:00 and 17:00 ET (celery_app.py:115-121). The
11:00 auto-pick run therefore publishes 03:30 prices, about 7.5 hours old, before the 12:00 refresh can flip
the side or the price. A published pick is never revisited (runbook, "Flow"). If the 17:00 refresh runs past
17:30, the evening run reads half-updated rows.
**Mechanism.** The pick is made at an early price that the market has since moved past. This shows up as the
negative CLV (F2 evidence). The size is not separable from F2 with the evidence available.
**Confidence.** CODE-ONLY.
**Register.** New.
**Fix (S).** Pass `"projected_at"` as `gen_attr` for every NBA prop spec, and add a hard gate for
`projected_at` older than 3h (or require `projected_at` after the latest pregame refresh). Optionally re-quote
from the odds snapshot table just before writing the bet.

## F7. The NBA board still labels "Best edges" picks for markets the gate withholds or never measures (frontend/API)

**What is wrong.** On the NBA predictions page, the "Best edges" card ranks rows by positive `edge` and shows
the `recommendation` side with a "Gamble It" button, for points, threes and PRA. The gate withholds points and
threes, and PRA has no record.
**Evidence.** `frontend/src/lib/propDiscoveryConfigs.ts:19-27` (NBA groups including Points, Three-Pointers
and PRA); `BestEdgesDiscovery.tsx:38-43, 116`; `lib/propDiscovery.ts:67-75` (top positive edge).
`api/v1/predictions.py:183-189, 908-914` strips pick labels only for `_NBA_NEW_MARKET_KEYS` = steals and
blocks. Points and threes are never passed through `record_gate.withheld_keys`, and PRA has no key in the gate.
**Confidence.** CODE-ONLY.
**Register.** New. The docstring at predictions.py:201 claims the opposite ("the board never labels a pick
that auto picks would withhold").
**Fix (S).** Map every NBA prop group (points, assists, rebounds, three_point, steals, blocks, pra) to its
record key in `predictions.py` so they all go through `_withhold_unproven_picks` with `loaders=("nba_props",)`.
That depends on F1 giving PRA a key. Do the same for the NFL spread, total and passing boards.

## F8. Under all of this: no measurable edge in NBA props (simply no edge)

**Evidence (11-17).** Every NBA prop market is below its true breakeven over 1,300-1,900 calls: points 47.9%
(-173.7u), rebounds 49.1% (-119.2u), assists 50.3% (-64.0u), threes 49.3% (-97.6u). Prob CLV is negative on
every market (-1.7 to -2.5pt). The fair-price shadow primary (assists/rebounds): n=85, CLV -1.1pt, ROI -5.5%,
H2 -3.7% (too small to decide; the 300 needed for a verdict is not reached).
**Size and luck.** Going 1-7 at a true 50% happens 3.5% of the time, and about 6% at 45%. The 8-bet record is
mostly bad luck on top of a negative-EV process. The process is negative EV whether or not this run of 8
continues: F1-F3 select the noisiest calls at -125 to -140 prices in markets that lose at those prices.
**Confidence.** CONFIRMED (evidence files).
**Register.** NBA-4 and X-1 cover this ground; this is the plain verdict.
**Fix.** Publish nothing from NBA props until a market clears breakeven **at real prices** on 300+ priced,
current-version calls, or until the fair-price rule passes its verdict. The fixes for F1, F3 and F4 make the
gate enforce that.

---

## Settlement / grading (question 6): no defect found

`yetai_grading._grade_game` (yetai_grading.py:561-604) gives: push when actual equals line (:412-414); void
for DNP or 0 minutes (espn_results.py:665-676); `not_ready`, then void after the retry window, for a player
not in the box score; void for an ambiguous name (exact-suffix match first, espn_results.py:646-659); the
nearest game by `commence_time` (:533); PRA = points + rebounds + assists (espn_results.py:139). Threes reads
the leading number of "3-7", which is correct. A name mismatch cannot become a loss: it becomes not_ready and
then void. I see no path that turns a DNP or a wrong player into a loss. The 7 losses are most likely real.
To confirm, run Q1 and check each `result` text ("Lost: <player> over X <stat> (N)") against the ESPN box
score.

## Queries that settle the open points (run read-only, by someone with access)

```sql
-- Q1: every settled/void bet since 11-01, with source, stat, book, price and pick-time numbers
SELECT id, source, status, sport, bet_type, selection, odds, model_version, created_at, settled_at,
       prediction_factors->'grading'->>'stat'           AS stat,
       prediction_factors->'projection_metadata'->>'book' AS book,
       prediction_factors->>'market_line'                AS line,
       prediction_factors->>'our_projection'             AS proj,
       confidence_score, result
FROM yetai_bets
WHERE settled_at >= '2026-11-01' AND status IN ('won','lost','pushed','void')
ORDER BY settled_at;

-- Q2: what the 139 "bets" created in 30 days really are
SELECT source, status, coalesce(model_version,'None') mv, count(*)
FROM yetai_bets WHERE created_at >= '2026-10-18' GROUP BY 1,2,3 ORDER BY 4 DESC;

-- Q3: run drop reasons and withheld keys per auto-pick run
SELECT id, run_at, status, candidates_considered, candidates_selected,
       dropped_reasons->'withheld_keys' AS withheld, dropped_reasons->'counts' AS counts
FROM auto_pick_runs WHERE run_at >= '2026-11-13' ORDER BY run_at;
```

Gate figures for assists, rebounds and pra: `python -m app.services.auto_pick gate` against a replica (F3).

## Smallest fixes, by bucket

| Bucket | Fix | Size |
|---|---|---|
| (a) Selection | Rank props by EV at the real price from a shrunk projection; require the consensus EV ≥ 0 (store `fair`/`ev` from `best_quote`); price must enter the score (F2) | M (interim gate: S) |
| (b) Gate | PRA into the gate plus prove-in (F1); grade priced rows only, or at the median stored price, not -110; raise the prior cap; scope by model_version (F3); turn on `AUTO_PICK_REQUIRE_PROVEN_RECORD` (F4) | S each |
| (c) Plumbing/audit | Review bets section AUTO-only and by game date; PRA loader; compare against the pick-time snapshot (F5); `projected_at` freshness gate (F6); board pick labels through the gate for every NBA prop key (F7) | S each |
| (d) No edge | Do not publish NBA props until a market beats real-price breakeven on 300+ current-version priced calls (F8) | policy |
