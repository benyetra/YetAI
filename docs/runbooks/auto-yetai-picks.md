# Auto YetAI Picks — Runbook

Each US Eastern slate day the system publishes the best 2-3 picks from that day's model projections to the
YetAI Bets section with no human step. Every published pick carries grading metadata so the settlement task can
take it to `won` / `lost` / `pushed` / `void`.

Settlement always runs, independent of every flag below: Celery `yetai_bets.settle` every 15 min (beat) and the
API process's own scheduler every 30 min (`BetSchedulerService`, started in `main.py`). Both are safe together
(row locks, `skip_locked`). Stale `pending_approval` rows are expired inside settlement too.

## Flow

Celery beat (timezone `America/New_York`) fires `auto_pick.yetai_bets` at **13:30 ET** and **18:00 ET**
(`candidate.MORNING_RUN_ET` / `EVENING_RUN_ET`). The NBA pregame refresh starts at 12:00 and 17:00 ET, so each run
reads lines and prices that are at most a few hours old, and each refresh has 90 / 60 minutes to finish first.
The 13:30 run passes `reserve_slots=1`: it publishes at most `max_picks_per_day - 1` picks (min 1). It reserves
only if some gate-passing candidate would still be pickable at the evening run (unknown start times do not count);
otherwise it fills to the cap now. The 18:00 run (`reserve_slots=0`, also the admin "fire now" default) fills the
day to the cap. There is no fill-to-2 floor any more: zero picks is a normal day. Each run:

1. Builds the ET slate window for "today" (`candidate.slate_window`).
2. Pulls candidates from every source in `backend/app/tasks/auto_pick.py::_build_providers`
   (NBA, WNBA, NFL, NHL, MLB game lines and props).
3. Applies the hard gates (including expected value and the record gate), ranks by expected value, and fills only
   the slots still open today.
4. Writes `YetAIBet` rows with `source='auto'`, `status='active'` and `prediction_factors.grading`.
5. Writes one `auto_pick_runs` row with drop-reason counts and the top rejected candidates.

A published pick is never edited or replaced by a later run.

## Flags

Beat runs inside the **celery-worker** service (`scripts/railway-celery.sh`, `worker --beat`); there is no
separate beat service. The worker reads every flag except the last row. The API reads only
`AUTO_YETAI_PICKS_ENABLED`, for the `/admin/pipelines` display.

| Flag | Default | Effect |
|---|---|---|
| `AUTO_YETAI_PICKS_ENABLED` | on (unset = on) | Registers the 13:30 and 18:00 runs and the pending-expiry job in beat. `false` / `0` / `no` / `off` is the kill switch: no new picks. Settlement is unaffected. |
| `AUTO_YETAI_PICKS_AUTO_PUBLISH` | `true` | `true`: picks go straight to `active`. `false`: legacy manual flow, picks are `pending_approval` until an admin approves them at `/admin/yetai-picks`. |
| `AUTO_YETAI_PICKS_MIN_SCORE` | `55` | No effect on straight picks since selection rule ev-v1 (picks are ranked and gated by expected value). |
| `AUTO_YETAI_PARLAY_ENABLED` | `false` | Also builds one 2-leg auto parlay (legs pass the same gates). |
| `YETAI_SETTLE_RETRY_DAYS` | `3` | Days a pick that cannot be graded is retried before it becomes `void` (anchored at the later of the game day and the first attempt day, so a game ESPN never lists voids about 4.5 days after it). Transport errors (ESPN down) void only after the 14-day backstop (`SETTLE_BACKSTOP_DAYS`). |
| `NEXT_PUBLIC_AUTO_YETAI_PICKS_ENABLED` (frontend) | `false` | Only hides a warning banner on `/admin/yetai-picks`; the page always renders. |

Changing a worker flag needs a celery-worker restart (beat reads env at import).

Tuning knobs live in the `scoring_config` row: `score_threshold` (default 65; parlays only since ev-v1), `odds_min` / `odds_max`
(-300 / +400), `max_picks_per_day`, and the six sub-score weights. The cap is clamped to 3 in code
(`config_loader.MAX_PICKS_CAP`), so a legacy row holding 4 still yields at most 3 picks; the alembic revision
`20261113_auto_pick_cap_3` also resets the row and runs in the deploy workflow
(`railway-production-deploy.yml`, job `migrate`, before the services deploy).

## Selection rules

- Daily cap: `max_picks_per_day` straight picks per ET slate day, counted across runs (published = any status
  except `rejected` / `pending_approval`; a `void` row does not use a slot, but its game stays excluded so the
  same game is not picked again). The morning run stops one short of the cap; the evening run fills
  the remaining slots.
- Diversity: at most 2 of the day's picks (counted across runs) per league + market type, e.g. NBA player
  props (drop reason `market_concentration`).
- Concurrency: each writing run takes a Postgres transaction advisory lock (`AUTO_PICK_LOCK_KEY` in
  `orchestrator.py`) before reading today's rows and holds it to commit, so overlapping runs (beat plus
  "fire now", or a redelivered task) cannot exceed the cap.
- Ranked by expected value (EV) at the published price, best first (see below). Every candidate that reaches
  ranking has already passed the EV gates; the confidence score is shown on the pick but never decides it. Zero
  picks is a valid day.
- One pick per game per day (game = league + ET date + teams).
- Tiers by rank: rank 1 FREE, ranks 2-3 PRO.

### Hard gates (drop reason recorded on the run)

| Reason | Meaning |
|---|---|
| `no_play` | The model did not name a side. Sources also skip NO_PLAY / PASS rows outright. |
| `non_positive_edge` | Edge for the picked side is zero or negative. |
| `odds_out_of_bounds` | Price outside `odds_min` / `odds_max`. |
| `stale_line` | The row's `projected_at` or its quote time `quoted_at` is older than the latest refresh start of ITS league (table below) or older than 3 hours. Also drops rows a still-running refresh has not reached yet. |
| `no_consensus_price` | No fair probability for the side: no multi-book consensus and no two-sided price. Nothing is made up; the candidate is dropped. Game lines (NBA, NFL), NFL passing / receiving yards and NHL saves / totals carry one too (see "Consensus price for game lines"). |
| `no_model_probability` | The market has no probability model and no consensus price. |
| `negative_consensus_ev` | At the market's own fair probability the price loses money (we would pay more than fair). A single book's two prices always fail this: their no-vig split prices the vig in. |
| `ev_below_threshold` | Blended EV is not above `ev.MIN_EV` (+2%). |
| `losing_record` / `unproven_record` | The record gate withholds the market (below). |
| `ungradeable` | `yetai_grading.can_grade(league, market, stat)` is false, so settlement could not grade it. |
| `started_or_starting` | Game started or starts within 20 minutes. |
| `start_time_unknown` | No start time and it is past 12:00 ET. |
| `injury_flag` | Source flagged the player/goalie (e.g. scratched). |
| `event_already_used` | A pick in this game was already published today. |
| `cap_reached` / `same_event` / `market_concentration` | Ranking outcomes. |

### Expected value (selection rule `ev-v1`, `auto_pick/ev.py`)

In plain words: we only bet when the price is at least as good as what the whole market thinks is fair, and our
model, trusted only a little, says the bet wins more often than that price needs.

1. **Market's fair chance.** For NBA props, the line shopper (`odds_math.best_quote`) reads ten books, removes the
   vig from every two-sided quote and takes the consensus; it stores that fair probability of our side at the best
   line (`best_fair_prob`), its EV (`best_ev`) and the quote time (`best_quoted_at`) next to the best book, line and
   price. A refresh that finds no quotes keeps the old quote and its old time, so the freshness gate drops it.
2. **Our small share.** The projection is pulled most of the way back to the line: our mean = line + k x
   (projection - line), with k = 0.10 (PRA 0.05). The review found the NBA points edge has a slope of about 0.10 and
   every prop model is worse than the line on lined rows, so trusting more than a tenth of the gap is not supported.
   Our share is P(side | that mean, the stat's market spread `odds_math.MARKET_SD`) - 50%. Moneylines: 0.10 x (model
   win probability - fair).
3. **Blend and price it.** p = fair + our share. EV = p x decimal(price) - 1 per 1u.
4. **Gates.** EV at the fair probability alone must be >= 0, and the blended EV must be above +2%.

So a bigger projection gap helps only a little, and a worse price always lowers the score: the same call at -115
ranks below it at +105, and a call at a price worse than fair is never picked however far the projection is from
the line. Each bet stores `prediction_factors.selection_version` ("ev-v1") and `prediction_factors.ev`
(fair_prob, model_part, prob, consensus_ev, ev); its reasoning text states the EV, price and both probabilities.
Changing k, MIN_EV or the formula means bumping `SELECTION_VERSION`, which starts a new bet record.

Known limits: in pending-approval mode (`AUTO_YETAI_PICKS_AUTO_PUBLISH=false`) a pending pick is not re-checked
for EV or freshness when an admin approves it later; parlays (off by default) use EV-gated legs but rank them by
confidence score and carry no EV block.

The confidence score (weighted sub-scores: edge, historical record, freshness, line movement, odds sanity, model
confidence; `sub_scores.py`) is still computed and stored for display. `score_threshold` and
`AUTO_YETAI_PICKS_MIN_SCORE` no longer affect straight picks.

### Record gate (`auto_pick/record_gate.py`)

A market (league, market, stat) must have earned its place on a record measured at real prices:

- **What is graded.** NBA props: the projection rows of the market's current model version (the version most rows
  on the latest date carry; older versions never mix in) that the selector would have considered, i.e. rows with a
  stored best price and consensus fair probability, inside the odds bounds, that pass the same EV gates, graded at
  `best_line` / `best_price`. It is every such row, not only the up-to-3 a day that the caps let through, and it
  is the row's last write of the day (the 17:00 refresh overwrites the 12:00 one). This is
  the **shadow record**: while a market is withheld its candidates are not written anywhere, but the ETL keeps
  writing and grading these rows, so the record keeps building and the market can prove in. Nothing in it can reach
  a user or the public bets record. Rows with no stored price are left out, never valued at -110. Other markets'
  loaders have no stored price, so their records count zero priced calls (shown as `unpriced_n`). AUTO bets count
  only for markets with no projection record, and only bets of the current selection version.
- **Arithmetic.** n = priced graded calls (no cap), shrunk ROI = units / (n + 20), which pulls small samples toward
  zero. Withheld losing: n >= 30 and shrunk ROI below -2% (n < 300) or below 0 (n >= 300).
- **Prove-in.** `AUTO_PICK_REQUIRE_PROVEN_RECORD` (default **true**) makes every market prove in: withheld unproven
  until n >= 100 over at least 10 slate dates (one night's rows share games, so they are not independent) and shrunk
  ROI >= 0. (At 30 calls a no-edge market shows a non-negative ROI about 40% of the time.) A market with no shadow
  source (MLB, WNBA, NHL shots, NFL anytime TD: no stored price) cannot build a priced record while withheld, so
  under prove-in it stays withheld until such a source exists. NBA / NFL spread, total and moneyline, NFL yards
  and NHL saves / totals now have one (priced shadow loaders in `record_gate`).
  `AUTO_PICK_PROVE_IN_KEYS` lists the markets that prove in even when that flag is false (default: NHL, NBA steals,
  blocks and PRA, NBA moneyline, MLB, WNBA).
- **Transparency.** `record_gate.all_key_rows(db, now)` returns every market's row (n, hits, units, n_eff, shrunk
  ROI, model and selection version, state open / withheld-losing / withheld-unproven);
  `python -m app.services.auto_pick gate` prints it.

WNBA spread and total sources (no stored consensus yet) still price from the game-lines table and handle a line
that moved after the projection ran: the edge is re-derived from the stored projected margin/total against the
CURRENT line, kept only if the side is unchanged and the new edge still meets the projector's own play threshold
(WNBA spread 2.0, WNBA totals 2.0). NBA and NFL game lines no longer do this: they use the consensus path below.

NBA / WNBA prop tables store the FanDuel price of the picked side in `fanduel_price` (written with the line by
`apply_fanduel_to_projection`, the PRA / threes generators and `etl/wnba/_prop_lines.py`). The prop sources publish
that real price; a row with no price (written before the column existed, or the book sent none) is skipped, and the
odds gate applies to props like every other market. If the migration `20261113_prop_fanduel_price` has not run, the
prop SELECT fails, is logged, and the prop source returns no rows.
Game-line markets without a stored price are skipped. The MLB hits board is
not a source (no market line or price stored). The NHL goalie-saves source is registered. Goalie rows are refreshed pregame at 16:45 ET
(`nhl.goalie_pregame_refresh`, gated by `NHL_PREGAME_REFRESH_ENABLED`) and carry a starter method
(`confirmed`: NHL boxscore or ESPN-confirmed; `probable`: ESPN `expected`, written at confidence 70; no history-based guess, it backtested at 60-65%).
Only `confirmed` starters are picked; `probable` ones are picked only with `NHL_GOALIE_PROBABLE_PICKS=1`
(default off: ESPN `expected` calls cannot be backtested, and a goalie who does not start is
"not in box score" and voids once the settlement retry window ends).

## Operations

### Turn auto-publish off (back to manual approval)

Set `AUTO_YETAI_PICKS_AUTO_PUBLISH=false` on celery-worker and restart it. New picks land as
`pending_approval`; approve them at `/admin/yetai-picks`. Unapproved picks are rejected at tipoff + 4h by
`auto_pick.expire_pending` (it never touches `active` picks). In this mode each run writes up to its cap with
no cross-run cap or game dedupe, so approving both runs' queues can publish more than 3.

### Stop everything

Set `AUTO_YETAI_PICKS_ENABLED=false` on celery-worker and restart celery-worker. Already-published picks still
settle. There is no settlement kill switch: `settle-yetai-bets` is not controllable from `/admin/pipelines`
overrides, so a grading bug needs a code revert.

### What `void` means

No action: game postponed/cancelled, player did not play, an admin pulled the pick, or it could not be graded
within the retry window. It shows in history with its reason and is excluded from W-L and units, like a push.

### Pull a published pick

`POST /api/admin/yetai-picks/{id}/reject` (admin). A `pending_approval` pick becomes `rejected`. An `active` /
`pending` pick becomes `void` with result "Pulled by admin": it leaves the live board, shows in history as void,
and is excluded from W-L and units. It frees its slot (the next run can add a replacement) but its game stays
excluded.

### Fire things by hand

- Auto-pick: admin Celery ops page ("YetAI auto-pick now", no kwargs = evening behaviour, `reserve_slots=0`), or
  `celery -A app.celery_app call auto_pick.yetai_bets --kwargs='{"reserve_slots": 1}'` for the morning
  behaviour. Pending expiry: `celery -A app.celery_app call auto_pick.expire_pending`.
- Settlement: `celery -A app.celery_app call yetai_bets.settle`, or the existing `/run-verification-now` endpoint.

### Diagnose a run

- `GET /api/admin/yetai-picks/runs/latest` or `/runs/{id}/diagnostics`: drop-reason counts, top rejected
  candidates, projection row counts per source for the ET slate day, hints.
- Dry run (no writes) against a database you point it at, never production:

  ```bash
  cd backend && DATABASE_URL=<staging-or-local> python -m app.services.auto_pick dry-run --date 2026-11-13
  ```

  Prints what would be published (selection, odds, score, tier, start time, grading block) and the drop summary.
  It defaults `now` to 13:30 ET but runs with `reserve_slots=0`, so it shows evening / fire-now behaviour (up to
  3 picks), not the 13:30 reserve behaviour.

### Add a source

Create a shim in `backend/app/services/auto_pick/sources/` that emits the dict shape documented in
`.factory/selection/artifacts/plan.md` / the provider modules (model-named side, stored price, both full team
names, ET `game_date`, naive-UTC `commence_time`, canonical stat key), register it in `_build_providers`, and
make sure `yetai_grading.can_grade` covers its league/market/stat or every candidate will be dropped as
`ungradeable`.

## Rollback

`AUTO_YETAI_PICKS_ENABLED=false` stops new picks. Reverting code after `void` rows exist makes them vanish from
history (the old code's visible set has no `void`): do not roll back the code once voids exist, or fix their
status first. The cap migration is data-only; `alembic downgrade -1` puts 4 back, but the code clamp still
yields 3.

## Consensus price for game lines and NFL / NHL props (build 2026-11-18, `20261118_game_best_price`)

NBA / NFL spread, total and moneyline, NFL passing and receiving yards, and NHL saves and team totals are
priced from the odds snapshots that every Odds API response already records (`consensus_price.best_fields`,
attached by the writers at write time as `best_*`; moneyline `ml_best_*`). The projector's own
recommendation, the moved-line re-derivation and the moneyline model-edge floor are not used on this path:
the EV rule and the record gate decide.

**The rule.**
- A book's quote counts only if it was seen in the last **30 minutes** and its update is within 30 minutes
  of the freshest book.
- **Same line only, at least 3 other books.** The best bettable book for our side is priced against the
  no-vig fair probability of the OTHER books quoting exactly the same line (spread: the same home point;
  total or prop: the same number). A book at another line is never converted. Fewer than 3 others at the
  line, a refused capture, or no event id means no quote: every `best_*` is stored as None and the
  candidate drops as `no_consensus_price`. Reference-only books (e.g. Pinnacle) never supply the price.
- Side: spread home if projected margin + home spread > 0, away if < 0; total / prop over if projection >
  line, under if <; moneyline home if the margin beats the margin the stored spread implies. Equal = none.
- **Model part of p** (p = fair + model part; EV = p x decimal - 1; gates unchanged: consensus EV >= 0 and
  EV > 2%): spread = logistic(k x (side margin + line) / scale) - 0.5 with the anchor's k and the league's
  logistic scale; moneyline = the same on the market margin; **totals, NFL / NHL props = 0**, so these
  only pass when the best book beats the market's fair price by more than 2%. NBA props are unchanged.
  A missing `anchor_k` / `model_margin` also gives 0.

**Freshness per league** (`candidate.refresh_starts_et`; a row is stale if its write or quote predates the
latest start; a test fails if these drift from `celery_app.py`):

| League | Refresh starts (ET) |
|---|---|
| NBA (and WNBA, MLB) | 03:30, 12:00, 17:00, 18:30; picks at 13:30 and 18:00 |
| NFL | 04:30 daily; Sun 10:00, 12:30, 15:30; Mon 17:00, 18:15; Thu 10:00, 17:00, 19:00; Sat 12:30 |
| NHL | 05:00, then :45 of even hours 10-20 (10:45 ... 20:45); a refresh rewrites only games starting within ~3 h, so a late game keeps its 05:00 row and is stale for picks |

**How long each key needs to prove in.** Prove-in needs 100 gate-passing priced rows and 10 slate dates, ROI
>= 0, on the current model version. The record counts every row that passes the EV gates (one row per game
or player per day, last write wins), not only the 2-3 a day that can be picked, so:

    weeks to 100 rows = 100 / (games per week x pass rate)
    weeks to 10 dates = 10 game days / game days per week

and the key opens after the LATER of the two. The pass rate (the share of rows with a consensus quote whose
best price beats fair by the 2% EV gate) is unknown before deploy; read it from the first week's
`unpriced` and `n` columns. Worked examples at assumed rates:

| Key | Volume | Rows / week at pass rate 20% / 50% | Weeks to 100 rows | Date floor |
|---|---|---|---|---|
| NFL spread (or moneyline, total) | ~14 games a week | 2.8 / 7 | 36 / 14 | 10 NFL game days = at least 4-5 weeks (Thu, Sun, Mon) |
| NBA spread / total / moneyline | ~45 games a week | 9 / 22 | 11 / 4.5 | 10 game days = ~2 weeks |
| NHL total | ~50 games a week | 10 / 25 | 10 / 4 | 10 game days = ~2 weeks |
| NHL saves | ~50 starters a week with a line | 10 / 25 | 10 / 4 | ~2 weeks |
| NFL passing / receiving yards | ~14 QBs / ~40 WRs with a line | 2.8-8 / 7-20 | 12-36 / 5-14 | 4-5 weeks |

NFL is the slow one: a single NFL week has at most 3 game days, so the date floor alone is 4-5 weeks, and at a
low pass rate the row floor (14-36 weeks) can outlast the season. A pass rate near zero means the consensus is
simply not beaten by any book, which is the honest answer. The rows only start counting on deploy day.

**Check qualifying rows per day for a game market** (read-only; NFL spread shown; swap the table and
`game_date` / `created_at` column for NBA / NHL totals). It counts rows with a consensus quote and a positive
consensus EV, per day; the record gate's own EV gates (odds bounds, blended EV > 2%) are applied in
`record_gate`, so this is an upper bound. Use `python -m app.services.auto_pick gate` for the exact n.

```sql
SELECT game_date,
       count(*)                                                     AS rows,
       count(best_price)                                            AS with_quote,
       count(*) FILTER (WHERE best_ev > 0)                          AS positive_consensus_ev,
       count(*) FILTER (WHERE best_ev > 0.02)                       AS above_2pct
FROM pred_nfl_spread_projections
WHERE game_date >= current_date - 28
GROUP BY game_date
ORDER BY game_date DESC;
```

For the moneyline use `ml_best_price` / `ml_best_ev`; for NHL totals the table is
`pred_nhl_team_totals_predictions` (`game_date`), for saves `pred_nhl_goalie_predictions`.
