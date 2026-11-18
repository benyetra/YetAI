# Fair-price shadow: the decision rule (fixed 2026-11-15; amended to `fp-shadow-v2` on 2026-11-17)

Companion to docs/edge-engine-design.md (Phase 1a) and docs/edge-engine-backtest-2025-26.md
(verdict INCONCLUSIVE, case (a): "build the live flags in shadow, publish nothing, decide after 300
live flags"). This file fixes, before the first live shadow flag is graded, what the live sample
is, what is measured, and what each outcome means. It is committed on its own, before the commit
that adds grading, so the history shows the rule came first. Changing anything below after
grading starts requires a new rule version and a fresh sample; the old sample is then reported
as it stands, never merged into the new one.

## Amendment, 2026-11-17: rule version `fp-shadow-v2`

Made by the owner's decision after the 2026-11-17 review (docs/projection-review-2026-11-17.md,
item B1), under this file's own terms: a change after grading starts means a new rule version and
a fresh sample.

- **Why.** The 300-flag sample was filling in days, not weeks (about 350 flags a slate), so the
  verdict would have rested on about five game dates. Intervals are clustered by game date; with
  so few dates the normal interval is far too narrow. The 11-17 review printed CLV -1.1 points
  [-1.2, -1.0] from two dates, where the honest half-width is about 1.1 points. Simulated with no
  true CLV, NO GO fired 6 to 7% of the time on four or five dates against the intended 2.5%.
- **What changed.** (1) The decision sample is the first graded primary flags, in the same order,
  up to the point where there are **at least 300 flags on at least 30 game dates** (so it is
  larger than 300 when 300 arrives early). (2) Intervals clustered by game date use Student's t
  on (dates - 1) degrees of freedom instead of 1.96. (3) H2 follows the same two changes.
- **What did not change.** The flag rule, the books, the weights, the metrics, the verdict
  thresholds and the 3,000-flag ROI stage. "300" below now reads "300 flags on 30 game dates".
- **The `fp-shadow-v1` sample, as it stood** (2026-11-17 review, not merged into v2): 85 graded
  primary flags on 2 game dates, CLV -1.1 points, hit 54.1% (46/85), -4.7u, ROI -5.5%; H2 69
  flags, CLV -1.0 points, ROI -3.7%. Too few dates to read either way. v1 flags stay in the table
  and are no longer flagged, counted or reported.
- **When to expect the verdict.** About 30 NBA game dates from the deploy, so late December 2026.
- The power table below was computed for date counts in the hundreds; under v2 the 30-date floor
  is what makes its 300-flag row roughly apply.

## In plain language
- Every 10 minutes the shadow flagger looks at the odds we already store and writes down every
  price that beats the fair price by at least 5%, exactly as it would publish it. Nobody sees it.
- After each game we check two things: did the market move toward our price by the close (CLV),
  and did the bet win money at the price we flagged (ROI).
- After 300 graded flags we read one verdict. 300 flags are enough to tell whether the live engine
  finds prices the market moves toward (the backtest said yes, by about 1.4 to 3 points), but
  far too few to tell whether it makes money: the ROI interval at 300 flags is about +-11 points
  wide. So the 300-flag checkpoint decides whether the signal is real live; a larger sample,
  fixed below at 3,000 flags, is what decides whether it is profitable.

## The rule being tested (rule version `fp-shadow-v1`)
- Engine: `app/services/fair_price/` as in the backtest: power de-vig, negative-binomial line
  conversion, logarithmic pool with fitted book weights, leave-one-out (a book is never part of
  its own fair price).
- Flag: EV >= 5% at the book's own line, >= 3 other books in the consensus, fair probability of
  the side in [0.15, 0.85], pregame only (observation and flag both before the scheduled start),
  observation no older than 30 minutes when the flagger reaches it.
- Books: the live `PROP_BOOKS` (fanduel, draftkings, betmgm, williamhill_us, espnbet, betrivers,
  hardrockbet, pinnacle, novig, prophetx), the list the backtest was bought and fitted on.
  pinnacle is reference-only; novig and prophetx are consensus-only
  (`FAIR_PRICE_CONSENSUS_ONLY_BOOKS`): they inform the fair price and are never flagged.
  Reason: they are exchanges whose posted prices are resting orders of unknown size, and in the
  backtest their flags barely beat the close (CLV +0.59 points against +2.82 at retail books).
  This choice was made after seeing the backtest, so the comparable backtest figure for the live
  primary sample is the retail-books cut (n=1,165, CLV +2.82 [+2.53, +3.11], ROI -0.4%
  [-6.2, +5.3]), which was exploratory there and is confirmatory here.
- Weights: the weights in force when the flag was made (recorded on the flag). The seed is a fit
  on every 2025-26 close we bought; a monthly refit adds the live closes, like the backtest's
  monthly walk-forward. Scheduled refits are part of the rule, not a change to it.
- One flag per (event, market, player, side, book): the first qualifying observation. Seeing the
  same price again later updates "last seen qualifying" and does not add a flag.

## Primary sample
- NBA `player_rebounds` and `player_assists` flags of rule version `fp-shadow-v1`, tier
  `primary`, whose first qualifying observation is not the game's closing observation (a flag made
  from the close has CLV positive by construction; such flags are counted and scored on ROI only,
  as in the backtest).
- Void flags are not bets: the player did not play, has no box score, or his name does not map
  to one player. They are counted and left out of every scored set, n included.
- In order of the flag's first observation time (ties by id), the **first 300 graded flags**.
  The sample is closed at 300 whatever the running numbers look like: no stopping early for a
  good or a bad run, no extension to rescue a result. Interim numbers in the daily review are for
  checking that the pipeline works, not for deciding.
- Other NBA prop markets, NHL and NFL props are flagged too, tagged `secondary`, reported
  separately, and never counted toward any decision.

## Metrics (identical definitions to the backtest)
- CLV = closing no-vig consensus probability of the flagged side at the flagged line minus the
  implied probability of the flagged price, in probability points. The close is the last
  observation before the scheduled start, de-vigged and pooled with the flag's weights, converted
  to the flagged line by the same line conversion. No CLV when the close is more than 60 minutes
  before the start (that is not a close) or when no book can be converted soundly; such flags
  stay in n, as in the backtest.
- Result at the flagged line from the box score (pushes count in n but are neither wins nor
  losses; did-not-play is void), units at the flagged price (+0.909 at -110 when won, -1 lost).
- Intervals: 95%, clustered by game date for CLV and ROI; Wilson for the hit rate.
- Random baseline: for each flag, one quote drawn at random (seeded) from the flaggable quotes
  present at the same moment, scored the same way. Placebo: the backtest's sign-flip placebo.

## Verdict at 300 (code: `fair_price/backtest.py` `decide`, unchanged)
- INVALID (fix the pipeline, the sample restarts under a new version): the placebo's mean ROI is
  more than 1.96 se from its coin-flip expectation, or the random baseline's CLV lower bound is
  above 0.
- GO: CLV lower bound > 0, ROI point estimate >= 0, and the paired difference (flag CLV minus its
  random baseline CLV) has a lower bound > 0. Action: build Phase 1b (publishing behind the
  record gate's prove-in key). It does not say the flags make money; the record gate and the ROI
  stage below decide that.
- NO GO: CLV upper bound <= 0. Action: do not publish; diagnose once (feed speed, weights,
  books), then stop.
- INCONCLUSIVE, otherwise: (a) CLV lower bound > 0 but ROI below 0: keep running in shadow to the
  ROI stage, publish nothing; (b) CLV interval spans 0: the live engine does not reproduce the
  backtest's signal; diagnose before running further.

## ROI stage: the first 3,000 graded primary flags
- PROFITABLE: ROI lower bound > 0. UNPROFITABLE: ROI upper bound < 0 (a NO GO for publishing as a
  money-making product, whatever the CLV). Otherwise: not distinguishable from break-even.
- Stated now: at 3,000 flags the ROI interval is about +-3.6 points, so it can separate +4%
  from -4% but not +2% from -2%.

## Power, honestly
From the backtest's primary flags (per-flag effective SD after date clustering: CLV 5.1 to 5.4
points, units 0.92 to 1.18; clustering changed the variance by less than 20%):
| n | CLV 95% half-width | ROI 95% half-width (retail) |
|---|---|---|
| 300 | +-0.6 points | +-11 points |
| 1,000 | +-0.3 points | +-6 points |
| 3,000 | +-0.2 points | +-3.6 points |
- 300 flags detect a true mean CLV of about +0.8 points with 80% power. The backtest's retail
  figure (+2.8) would be detected easily; its all-books figure (+1.35) very likely.
- 300 flags cannot separate the backtest's -3% ROI from +3%: the two are about half an interval
  width apart. Separating them (+-3 points) needs about 4,300 retail flags; detecting a true +3%
  ROI with 80% power needs about 8,700. 3,000 is the pre-set compromise above.
- A useful cross-check that needs no extra sample: if the no-vig close is calibrated, a flag's
  expected ROI is about its CLV times its decimal price (about 2 x CLV near even money). ROI far
  below that, sustained, says the close itself is biased at these books.

## Secondary hypothesis (pre-registered from the backtest)
- H2: retail books excluding espnbet (backtest, chosen after seeing the data: n=955, CLV +3.20
  points, ROI +2.4% with interval -3.5% to +8.2%).
- Sample: the first 300 graded primary flags whose book is not espnbet (a subset of the primary
  stream, so it closes later). Same verdict rule and thresholds as the primary; ROI stage at its
  first 3,000.
- It never changes the primary verdict. If the primary is not GO and H2 is GO, the action is to
  build Phase 1b with espnbet added to the consensus-only books. Two hypotheses at 95% each: the
  chance that at least one passes by luck when neither is real is up to about 10%, not 5%.

## What the daily review shows
Flags yesterday and to date (primary and secondary), progress toward 300 and 3,000, CLV, hit
rate, units and ROI with intervals, by book and by hours before the start, how many flags were
still available at the playable-to price at the next snapshot, and, once a sample is complete,
the verdict computed by this rule. When the snapshot table has no recent rows the review says so
instead of showing zero flags as if it were a result.
