# Projection and YetAI Bets review (2026-11-17)

> What was built from this review, and what to expect after deploy: [`docs/build-2026-11-18.md`](build-2026-11-18.md).

What is still broken after the 11-13 to 11-15 repairs (PRs #177 to #188), and why the projections and
the YetAI Bets auto picks keep missing. Follows `docs/projection-issues-2026-11-13.md`; IDs there
(NBA-4, X-1 and so on) are reused here.

## Bottom line

1. **The auto picks lose because of how they are chosen, not because of a grading fault.** Since
   11-14 the system has published two NBA props a day and nothing else, and they are 0-6 (props 1-7
   overall, -6.00u). About four of the six were PRA picks, a market the record gate does not
   measure at all. The selector ranks bets by how far the projection sits from the line and ignores
   the price, so with a model that has no edge it picks the model's largest errors.
2. **The projections miss because no model beats the line, and that has not changed.** The
   11-14 repairs held (NBA box scores, NHL inputs, NBA game-market anchor), and the newest days are
   no better: every NBA prop is still worse than the line on error and negative in units at real
   prices. The plumbing is now mostly right; the models are mean estimators that track the line at
   best. Nothing in any model uses rotation, injury or teammate-out information.
3. **Three of the yardsticks are wrong, and two of them feed decisions due this week.** The
   fair-price shadow interval is about ten times too narrow, the NBA "prob CLV" has a built-in
   negative offset, and the daily email compares projection error and line error on different rows,
   so it reads as if the projections beat the line.
4. **Users still see picks from markets the gate withholds.** The NFL board withholds nothing. The
   NBA "Best edges" card shows points, threes, PRA and even withheld steals with a Gamble It button.

## How this was done, and its limits

- Four parallel code reviews of production's code (main at `5b662edf`), then two independent passes
  that tried to disprove the main claims by re-reading the code and running the real functions with
  made-up inputs. Corrections from those passes are folded in below.
- Production numbers come from the Daily Model Review workflow logs of 11-14 to 11-17. Their counts
  are cumulative, so day-over-day differences isolate the newest days.
- **No direct production database access in this review.** Anything that needs a row-level query is
  marked "to confirm" with the query in the detail files.
- The daily review runs in GitHub Actions without production's `AUTO_PICK_*` settings, so its gate
  section shows default settings, not necessarily production's.
- Confidence: **Confirmed** (code and data agree, or reproduced by running the code), **Code only**
  (code is clearly wrong; no data to size it), **Hypothesis** (plausible; needs the named query).
- Detail with `file:line` for every item: `docs/reviews/2026-11-17/`.

## Why the signature bets lose

| Step | What happens | Confidence |
|---|---|---|
| 1. What may publish | Prove-in mode is still off (YetAI-e7g). On an NBA night the open markets are assists, rebounds and PRA. Points and threes are withheld as losing. | Confirmed |
| 2. PRA has no gate | PRA is a registered pick source with no projection record in the gate and is not on the prove-in list. Its only record is its own bets (4), which can never reach the 30 needed to withhold it. The PRA projection is points + rebounds + assists, so the withheld points error comes straight back in. | Confirmed |
| 3. How picks are ranked | The score is 40% "projection minus line", capped per stat. Run with the real scorer: at the same gap, every price from -150 to +150 scores 62.5; a PRA gap of 6 scores 82.5 at any price. No shrinkage toward the line, no expected-value check. The best-book quote computes a consensus EV and then discards it, so negative-EV quotes pass. | Confirmed |
| 4. Why big gaps are bad bets | Points calls 3+ from the line hit 50.0% (n=336); assists calls 2+ from the line hit 45.2% (n=42). The gap is mostly model error. | Confirmed |
| 5. Stale inputs | The 11:00 ET pick uses the 03:30 run's projections and prices, an hour before the 12:00 refresh. Prop candidates carry no freshness check. | Confirmed |
| 6. Gate leniency | Graded calls with no stored price are valued at -110; prices have only been stored since 11-13, so about 80% of the record is. Real median prices on the called side are -125 to -140. At -110 a market stays open down to about 51%; at -125 it would need 54.5%. NBA props and NFL are not scoped to the current model version. | Mechanics confirmed. Whether this is what keeps assists and rebounds open is a hypothesis: the report prints only withheld markets. |
| 7. No edge underneath | 30-day hit rates at the stored side: points 47.9%, rebounds 49.1%, assists 50.3%, threes 49.3%, against real breakevens of 53.5 to 58.3%. | Confirmed |

Settlement was checked and no defect found: pushes settle as pushed, did-not-play and unmatched
names as void. The seven prop losses look real. Going 1-7 at a true 50% happens about 3.5% of the
time, so this run is bad luck on top of a process that loses money on average.

The "YetAI Bets record" in the daily review also counts manual rows and windows on settle date. The
WNBA 2-0, the two "Could not parse pick" voids and probably the four spreads and one moneyline are
old rows re-graded by #175, not auto picks (hypothesis; query Q1 in `bets.md`). The auto-pick record
proper is most likely 1-7.

## What is still broken

Size: S under a day, M a few days.

### A. What gets published

| ID | Problem | Confidence | Fix | Size |
|---|---|---|---|---|
| A1 | PRA publishes with no record check (new). | Confirmed | Add PRA to the gate's NBA loader and the prove-in list, or drop the PRA source until points is admitted. | S |
| A2 | Selector ranks by gap and ignores price (NBA-4, selector side new). | Confirmed | Rank on expected value at the real price from a projection shrunk toward the line; store the consensus EV from the best-quote step and require it to be at least 0. | M (interim hard gate: S) |
| A3 | Gate values unpriced calls at -110, caps the sample at 60, and is not version-scoped for NBA props and NFL (X-1, NBA-8). | Mechanics confirmed | Grade priced rows only, or value unpriced rows at the stat's median stored price; scope to the current model version; print every key's gate row in the review, not only withheld ones. | S |
| A4 | Prove-in mode off (YetAI-e7g): PRA, NBA moneyline and NFL receiving yards can publish with an empty record. | Confirmed | Owner decision; a switch. Does not fix A3. | S |
| A5 | NBA board: picks are stripped only for steals and blocks. "Best edges" ranks by an edge value that stripping never clears, so points, threes, PRA and withheld steals all show with a Gamble It button. The code's own docstring claims the opposite. | Confirmed (worse than first reported) | Pass every NBA prop group through the withholding helper and clear the edge as well as the label. | S |
| A6 | NFL board: the endpoint never calls the withholding helper. Spread (30 days 31%, 90 days 45%, week 10 0 of 5), totals (90 days 45%), receiving-yards and anytime-TD picks all show. The frontend rebuilds a spread side when the backend stores none. | Confirmed | Call the helper in the NFL endpoint; remove the frontend fallback. | S |
| A7 | NHL board still exposes edge and projection-vs-line while picks are withheld; kickers shown with no signal (NFL-6). | Confirmed | Same treatment as A5; hide kickers. | S |
| A8 | 11:00 ET pick runs before the 12:00 refresh; no freshness gate on props; NFL Monday 18:00 and Thursday 19:00 refreshes run after the last pick (17:30). | Confirmed | Move the first pick after the midday refresh; pass `projected_at` into the freshness score. | S |

### B. Yardsticks that are wrong

| ID | Problem | Confidence | Fix | Size |
|---|---|---|---|---|
| B1 | **Fair-price shadow interval.** The printed CLV of -1.1pt [-1.2, -1.0] is clustered on two game dates (8 and 77 flags); reproduced with the repo's own function. The honest width is about ±1.1pt. The 300-flag decision will arrive around 11-20 on about five dates; simulated with zero true CLV, "no go" fires 6 to 7% of the time against the stated 2.5%. The negative CLV itself is not a vig artifact (a flag starts about +2.4pt ahead), so it may be real; it is just not established. | Confirmed | Owner decision, because the rule was committed in advance: before the 300th flag, add a minimum number of game dates (30 suggested) and a t-interval on dates. | S |
| B2 | **NBA prob CLV.** It compares the pick's with-vig price with a no-vig close, so a zero-skill call scores about -1.2 to -3.5pt. For points, threes and steals the "close" is the same 17:00 fetch that set the line (close capture only fetches rebounds and assists), hence line CLV exactly 0.00 and "close 142 min before start". Correct reading: no measurable CLV in any market, not negative CLV. | Confirmed | Compare no-vig with no-vig; capture closes for all prop markets; drop closes more than 60 minutes before start. | S |
| B3 | **Daily email error comparison.** Projection error is over all graded rows, line error only over rows with a line ("assists MAE 1.39, line MAE 1.71"). On the same rows the projection is worse (1.76 vs 1.71). | Confirmed | Compute both on lined rows. | S |
| B4 | The review cannot judge the new models: only NBA totals and spread are split by model version. No accuracy line for NFL anytime TD, NHL shots or NBA PRA. NHL saves CLV can never join ("j swayman" vs "jeremy swayman"). No thin-board row-count check (X-10). | Confirmed | Add a "current version only" view, the missing loaders, a name normaliser, and expected row counts. | S to M |
| B5 | The bets record in the review mixes manual and re-graded legacy rows and windows on settle date. Bets are compared with a projection row that later refreshes overwrite. | Code only | Auto picks only, by game date; compare with the bet's own pick-time snapshot. | S |
| B6 | Old stored pick sides (before 11-10) were never recomputed (NBA-11), so the review's 30-day hit rates and the audit's disagree (rebounds 49.1% vs 52.2%). On new rows they match exactly. The gate drops those rows rather than mis-grading them, so this is a reporting fault only. | Confirmed | Recompute stored sides for old rows, or grade projection vs line in the review. | S |
| B7 | NFL QB promote check on 11-10 said the model beats the line; on rows with a real line the line is better (55.1 vs 57.0). The baseline was padded with missing or imputed lines. | Confirmed | Restrict the check to real-line rows. | S |
| B8 | The review's credits section is empty in GitHub Actions (no Redis or API key there). Production's own 09:45 email should carry real numbers. Estimated burn 320 to 460 a day, so the plan lasts to the 12-14 reset. | Code only | Drop the section from the Actions run or label it. | S |

### C. Training loop

| ID | Problem | Confidence | Fix | Size |
|---|---|---|---|---|
| C1 | The NBA prop retrain promotes on champion holdout error only; nothing requires beating the stored line (X-2, YetAI-3tl). For points the line comparison is always empty (n=0) because the line loader only builds rebounds and assists. On 11-16 rebounds was promoted for a 0.00016 gain while worse than the line on its own holdout (2.034 vs 1.959, side hit 50.2%). | Confirmed | Add the line gate to the prop trainer and a points line join; require a minimum improvement. | S |
| C2 | The weekly retrain goes red on an ordinary "rejected by champion" (11-14, 11-16): the step exits before its own "treat as warning" logic. No stat is skipped, but a real failure now looks the same as a normal one. | Confirmed | Capture the exit code instead of letting the shell stop. | S |
| C3 | The residual shadow model has no rows because none existed until 11-16; only assists was uploaded and rebounds failed its line gate. Not a bug; expect assists rows from 11-17. | Confirmed | None; check the 11-18 review. | n/a |
| C4 | Training rows without a stored game line get 0 for game-line features and `is_home`; players with 1 to 4 current-season games get no projection. | Code only | Use nulls and a fallback sample. | S |

### D. By sport

| Market | State | Why it misses | Smallest fix |
|---|---|---|---|
| NBA points, rebounds, assists, threes | Plumbing fine, no edge | Box-score features only. Expected minutes are computed and never read; no teammate-out adjustment, so team-wide leans persist (Bucks, Mavericks, Rockets, Wizards over; Thunder, Magic under). Games of 11-15 and 11-16 at real prices: points 50.2% of 209 (-6.4% ROI), rebounds 53.5% of 185 (-1.0%), assists 48.4% of 153 (-11.7%), threes 52.9% of 153 (-7.8%). | Withhold (A1 to A3). The only item with a plausible path to an edge is minutes and teammate-out features (M). |
| NBA PRA | Gate gap | Sum of three projections, unmeasured | A1 |
| NBA totals, spread, win probability | Fixed and verified | Anchored to the market; cannot publish a call | None |
| NFL spread, win probability | No edge, still calling | Still the Elo model on the shared basketball config, unanchored; bias +3.8 over 30 days, +6.3 in week 10 (NFL-7, YetAI-ld0) | Reuse the NBA anchor helper; no calls until then |
| NFL totals | No edge | Unshrunk points-per-game average; 57.9% at n=38 is noise against 32 of 71 over 90 days (NFL-8) | Same anchor |
| NFL QB passing yards | No edge, no calls | With the ML flag on, the published number is the line plus noise, so rows are passes. The 6 of 18 is pre-fix history. Week 10: error 66.5 vs line 67.0 on 23 rows (NFL-2). A re-projection can change the yards without clearing an old call; `limit(32)` remains. | Decide the flag (YetAI-bzv); clear the call on re-projection |
| NFL receiving yards | Measurement broken | The 21 graded rows are the 11-10 rows labelled week 9 with week-10 lines, graded against week-9 yards (by elimination; to confirm by query). The real 188-row board is first graded on 11-19 because the grader only looks at the previous week. A mean projection against a median line probably explains the 60-to-3 over lean (hypothesis). | Delete the 26 mislabelled rows; grade the current week; re-centre |
| NFL anytime TD | Unmeasured, still calling | Absent from the review and the gate; QB prior about 3% a game against 17% observed (NFL-4); frozen by date only, so the Sunday 12:30 and 15:30 runs can rewrite rows of games already under way (X-6 is not fixed here) | Stop the calls (YetAI-mgo); add a review loader; freeze at kickoff |
| NHL shots, saves, totals | Plumbing fixed, no edge | #183's input fixes are verified in code. Saves are 0.3 worse than the line every day; totals 1.90 vs 1.85. The 05:00 run writes a week of games; matinees are never refreshed (YetAI-ph9). | Keep in shadow; restrict the run to today |

## Verified as fixed

- NBA box-score dating and duplicates (#182); training data is clean from 11-14.
- NBA totals, spread and win probability anchored to the market (#181). The +4.67 and -4.51 biases
  in the two review sections are the same number with opposite sign conventions.
- NHL inputs (#183): current-season team stats, no 20-game cap, all skaters, per-season goalie stats,
  team lookup by id, preseason filtered, roster-based skater selection.
- NFL QB classifier-only calls removed (#177).
- Settlement and grading of YetAI Bets.
- Odds snapshots for ten books and real prices on rows (from 11-13 and 11-14).

## Decisions for the owner

1. **Turn on prove-in mode now** (`AUTO_PICK_REQUIRE_PROVEN_RECORD=true`, YetAI-e7g). Recommended.
   It stops PRA, NBA moneyline and NFL receiving yards today. Assists and rebounds would still pass
   until A3 lands. Reversible.
2. **Pause auto picks until A1 to A3 are in** (`AUTO_YETAI_PICKS_ENABLED=false`). Recommended: the
   process loses money on average as built, and the fix is a few days. Reversible.
3. **Amend the fair-price decision rule before the 300th flag** (about 11-20). Recommended: require
   at least 30 game dates. Otherwise the go or no-go will be decided on about five nights. The rule
   was committed in advance, so the change should be recorded as an amendment with its reason.
4. **`NFL_QB_ML_ENABLED`**: the model adds nothing to the line. Leave on as a tracker or turn off so
   the soft anchor publishes; either way no calls result. Low stakes.

## Recommended order

1. Decisions 1 to 3 (switches and one document; no build).
2. Stop the visible losing picks: A1, A5, A6, A7, plus stopping anytime-TD calls. All S.
3. Fix the yardsticks before reading any more results: B1, B2, B3, B6, C2. All S.
4. Make the gate honest: A3, then A2 and A8.
5. Stop promoting models that lose to the line: C1, B7.
6. NFL: anchor spread and totals (YetAI-ld0), receiving-yards grading, anytime-TD freeze and loader.
7. Only then model work: NBA minutes and teammate-out features, measured against the line with the
   corrected yardsticks. This is the one item here that could create an edge rather than stop a loss.

## Detail files

`docs/reviews/2026-11-17/`: `bets.md`, `nba_props.md`, `nfl_and_game_markets.md`, `nhl_and_infra.md`
(first-round findings with `file:line`, evidence and queries), `verify_bets_board.md` and
`verify_measurement.md` (the disproof passes; where they differ from a first-round file, the
verification file is right).
