# Edge strategy: how the lines are made and where YetAI can have a real advantage (2026-11-14)

Built from three sourced research reports (how sportsbooks make lines; where winning bettors get
their edge; how professional prop projections are built) and from YetAI's own measurements against
production results (docs/projection-issues-2026-11-13.md). Claims from the research carry a source
link. Sections marked "Judgement" are our reasoning, not sourced fact.

## The honest answer

YetAI cannot become "as strong as the bookmakers" at predicting outcomes, and it does not need to.

- Closing lines on sides and totals are efficient after the vig in every major US league
  ([Moskowitz 2021](https://econpapers.repec.org/RePEc:bla:jfinan:v:76:y:2021:i:6:p:3153-3209),
  [Levitt 2004](https://www.nber.org/papers/w9422)). Our own data agrees: the fitted weight on our
  NBA game models was about zero.
- The books' prop engines are possession-by-possession simulations fed by hundreds of daily-updated
  player ratings ([DraftKings, Data+AI Summit 2024](https://microsites.databricks.com/sites/default/files/dais/2024/D241751B_How%20To%20(Maybe)%20Make%20Money%20Betting%20On%20The%20NBA%20Using%20Rocket%20Science%20V3_1717677883986001pwuO.pdf);
  [Huddle](https://huddle.tech/wp-content/uploads/2024/03/NBA-Player-Proposition-Micro-Markets-From-Creation-to-Resulting.pdf)).
  A box-score regression cannot out-predict that at the close, which is what we measured.
- The advantage that exists is not "a better number at the close". It is **price** (books
  disagree with each other), **timing** (books re-price props slowly after news) and **coverage**
  (thin markets get little sharp correction). Professionals who win at props do it this way, with
  edges of about 2% per bet, and are capped by limits
  ([The Ringer on Peabody](https://www.theringer.com/2022/9/21/23363621/gamblers-super-bowl-props-rufus-peabody-nfl);
  [ETR](https://establishtherun.com/miller-why-prop-betting-is-profitable/)).

So the strategy is: stop trying to beat the closing line with a model, and build the three things
that the evidence says work, measured by closing-line value from day one.

## How a prop line is made (what we are up against)

1. A game-level projection (team totals, pace) anchored to the spread and total.
2. A playing-time projection per player, then per-possession rates, then a simulation that assigns
   each event to players. Props, alternate lines and same-game-parlay correlations all come from
   the same simulation.
3. The operator adds its hold (props are typically -110 to -120 a side) and low limits.
4. Three things then move the line: model re-runs on news, the book's own betting action, and
   other books' prices. Vendors openly feed "industry market updates" and consensus lines into
   their pricing, so several books can share the same stale input.
5. There is no sharp prop book. Market makers (Pinnacle, Circa) post thin prop menus late; among US
   books FanDuel and Caesars are described as the most efficient on props
   ([ETR 2023](https://establishtherun.com/understanding-the-current-ecosystem-of-nfl-player-props/)).
6. On injury news books void the player's props and re-price related ones, with a gap. In one
   documented case props were pulled about 90 minutes after the announcement
   ([ESPN via ABC7](https://abc7ny.com/post/bettors-capitalize-on-nets-approach-to-mikal-bridges-resting/14235669/)).
7. Winners are profiled and limited, especially on props (reported caps of $15 to $100 after
   limiting). Parlay hold runs 15 to 25%.

## Where real edges are documented

| Edge source | Evidence | Open to us? |
|---|---|---|
| Fair price from a consensus of books, bet the outliers ("top-down") | Strongest. +3.5% over 56,435 bets in a 10-year backtest; +6.2% over 672 live and paper bets ([Kaunitz et al.](https://arxiv.org/abs/1710.02824)). About 30% of displayed edges had moved when checked; authors were limited within weeks. | Yes. Needs no model. Must be delivered with a price threshold and fast. |
| Speed on injury and lineup news | Opening lines mis-price NBA absences, closing lines do not ([Dare et al. 2015](https://ideas.repec.org/a/eee/finlet/v13y2015icp130-136.html)). Books react on main markets first; derivative props lag. No public measurement of the window. | Yes, and nobody has published the measurement, so we would have to build it. |
| Thin markets (WNBA, secondary props, low-profile stats) | Moderate. WNBA efficiency rejected at the 10% level ([Paul & Weinbach 2014](https://mdpi.com/2227-7072/2/2/193)). Limits are small. | Yes, with limits stated to users. |
| A better model, blended with the market | A top professional's best NFL blend is 45% model, 55% market ([Peabody](https://www.rotowire.com/football/article.php?id=40172)). The one academic test of an independent prop model was negative ([Univ. of Malta](https://www.um.edu.mt/library/oar/handle/123456789/115275)). | Only as a minority weight, after the model is rebuilt on the professional architecture. |
| Blanket biases (unders, star overs) | Existed; largely arbitraged. NBA-partnered books barred unders on players projected under 12 minutes on 2026-10-16. | No. |
| Same-game-parlay correlation, boosts | Weak or account-specific. | No, except as user education. |

Two facts shape everything else:

- **Publishing destroys an edge unless it is price-aware.** Publishing value picks "cannibalizes
  the value for most of your clients" (Peabody). A respected projection service moves prop markets
  within 10 minutes of release ([InGame 2026](https://www.ingame.com/?p=53210)). A pick must carry
  the book, the price, and a "playable to" price, or its edge is lost on the way to the user.
- **Closing-line value is the yardstick.** It detects an edge in tens to hundreds of bets; win/loss
  needs thousands ([Data Golf](https://datagolf.com/analyzing-betting-odds)). It must be measured
  against the no-vig close: many bets that beat the raw close still lose after the margin
  ([Whelan 2026](https://www.karlwhelan.com/?p=2595)).

## The plan (Judgement)

Each phase has a measurable test and a stop rule. Nothing publishes a pick until its market has
proved in under the existing record gate.

### Phase 0: measurement (built; PR #184)
Multi-book snapshots of every line and both prices, best price per projection, grading at the
real price, and closing-line value in the daily review.
- To add: closing-line value against a **no-vig consensus** rather than one book's close, and a
  "playable to" price on every published pick.
- Test: within two weeks, every graded call has a closing quote and a CLV number.

### Phase 1: fair-price engine (top-down, no model)
For each prop: remove the vig from each book (power or Shin method;
[Clarke et al. 2017](https://www.sciencepublishinggroup.com/article/10.11648/j.ajss.20170506.12)),
blend the books into a fair probability with weights fitted per sport and market from our own
closing history, and flag any book whose price beats fair by more than a threshold. Never mix a
price from one line with another line's number; convert between lines with a count distribution.
- Deliver as a live flag: book, price, fair price, expected value, playable-to price, expiry.
- Test: over the first 300 flags, mean CLV against the no-vig consensus close is positive, and
  ROI at the flagged price is not negative. Start the threshold near 5% (what Kaunitz and Data
  Golf needed) and lower it only if the data supports it.
- Stop rule: if 300 flags show no positive CLV, the consensus weights are wrong or the feed is
  too slow; fix those before anything else.
- Backtest before building further: the Odds API historical endpoint has prop snapshots at
  5-minute intervals since May 2023, for all books in a region in one call. Last season's NBA
  props would test this strategy on a full season offline.

### Phase 2: news-speed engine
Turn the official NBA injury report (updated every 15 minutes), starting lineups (due 30 minutes
before tip), NHL goalie confirmations and NFL inactives into re-priced props within minutes, and
flag props whose line has not yet moved.
- Needs a playing-time and availability model (probability of playing, starter flag, minutes
  given role, teammate absences, blowout risk from the spread) and a structural redistribution of
  an absent player's shots, rebounds and assists across teammates.
- First build the measurement nobody has published: for every status change, record when each
  book's line moved. That event study tells us how long the window is and whether it is worth
  building for.
- Test: on flagged props after a news event, the line subsequently moves toward our number
  (positive CLV) in a clear majority of cases over 200 events.
- Stop rule: if books re-price or suspend before our snapshot cadence can see a stale line, this
  needs a faster odds feed than we have, and the cost has to be weighed first.

### Phase 3: rebuild the projection on the professional architecture
Game environment from the market x playing time x per-possession rates x allocation among
teammates, simulated to a full distribution.
- Per-stat memory, not one rolling window: role changes within 1 to 3 games, while usage, assist
  and rebound rates take 17 to 54 games to move ([DARKO](https://www.darko.app/about)).
- Tracking inputs for rebounds and assists (rebound chances, potential assists, touches), as a
  hypothesis to test: no public source measures their gain.
- Scale player projections to the market's team total. Calibrate over/under probabilities and
  choose models on calibration, not accuracy ([Walsh & Joshi](https://arxiv.org/abs/2303.06021)).
- Use it as a minority weight on top of the Phase 1 fair price, fitted out of sample, never alone.
- Test: matches the closing line's error on lined rows (the realistic target), and earns a
  positive fitted weight in the blend out of sample.
- Stop rule: if the fitted weight is not distinguishable from zero after a full walk-forward
  season, the model stays display-only.

### Phase 4: publishing discipline
- Every pick: timestamp, book, price, stake in units, playable-to price. Results reported by
  market as ROI with intervals and CLV against the no-vig close, including losing categories.
- Stakes from a shrunken (fractional) Kelly rule
  ([Baker & McHale 2013](https://econpapers.repec.org/RePEc:inm:ordeca:v:10:y:2013:i:3:p:189-199)).
  The rule exists in the code and is switched off.
- Tell users plainly that retail books limit winners and that a flagged price expires.
- Watch regulated prediction markets (Kalshi, Novig, ProphetX): they list NBA props with caps
  around $10,000 a trade and do not limit winners; their prices are already in our odds feed.

### What not to do
- Do not try to beat closing sides, totals or moneylines. Keep them market-anchored.
- Do not sell blanket over or under systems, parlay-correlation picks or boost chasing.
- Do not publish a model pick without a price threshold.
- Do not call any bet "low risk". A good bet has positive expected value and still loses often.

## Costs and decisions

| Item | Cost | Why |
|---|---|---|
| Odds API 100K plan, one month | $59 (currently $30) | Covers today's higher daily usage and a historical backfill of last season's NBA props. The same purchase tests Phase 1 on a full season and gives the residual model ten times its data. |
| Higher plan if Phase 1 runs live across sports | $119 a month (5M credits) | Only if the backtest supports going live. |
| A consensus "sharp line" feed (for example Unabated) | about $799 a month (third-party figure, unverified) | Not needed to start; our own weighted consensus is the first attempt. |
| Faster odds feed for Phase 2 | unknown; quotes only | Decide after the event study shows how long the news window is. |

Licence checks before building on them: commercial use of NBA Stats tracking data and MLB Statcast;
MoneyPuck data is non-commercial only without an agreement.

## Sequence

1. Deploy PR #184 (Phase 0).
2. Buy one month of the 100K plan; backfill last season's NBA props for all US books; backtest
   Phase 1 offline. This is the decision point: it either shows positive CLV and ROI at realistic
   thresholds or it does not.
3. If it does: build the live fair-price flags (Phase 1) and the news event study (start of Phase 2)
   in parallel, both in shadow.
4. Build the playing-time model, which Phases 2 and 3 both need.
5. Phase 3 and the blend, last.

## What the research could not establish

- Any peer-reviewed study of prop-market efficiency or of how fast prop lines react to news.
- Whether opening prop lines are measurably softer than closing ones.
- How close an independent model gets to the closing prop line.
- Which vendor prices each major US book's props today.
- Whether Pinnacle or Circa prop prices are available through the feeds we can afford.
