# Auto YetAI Picks — Runbook

Each US Eastern slate day the system publishes the best 2-3 picks from that day's model projections to the
YetAI Bets section with no human step. Every published pick carries grading metadata so the settlement task can
take it to `won` / `lost` / `pushed` / `void`.

Settlement always runs, independent of every flag below: Celery `yetai_bets.settle` every 15 min (beat) and the
API process's own scheduler every 30 min (`BetSchedulerService`, started in `main.py`). Both are safe together
(row locks, `skip_locked`). Stale `pending_approval` rows are expired inside settlement too.

## Flow

Celery beat (timezone `America/New_York`) fires `auto_pick.yetai_bets` at **11:00 ET** and **17:30 ET**.
The 11:00 run sees only the overnight NBA data (props not widely posted, before the 12:00 / 17:00 pregame
refreshes and the 14:00 MLB pipeline), so its beat entry passes `reserve_slots=1`: it publishes at most
`max_picks_per_day - 1` picks (min 1) and does not fill from the floor. It reserves only if some scored,
gate-passing candidate would still be pickable at 17:30 ET (`candidate.EVENING_RUN_ET`, the same constant the
beat entry uses; unknown start times do not count). On an early-only slate (NFL early window, day games) it
behaves like the evening run: full cap and floor fill. The 17:30 run (`reserve_slots=0`,
also the admin "fire now" default) fills the day to the cap and, if the day has fewer than 2, to 2 from the
floor. Each run:

1. Builds the ET slate window for "today" (`candidate.slate_window`).
2. Pulls candidates from every source in `backend/app/tasks/auto_pick.py::_build_providers`
   (NBA, WNBA, NFL, NHL, MLB game lines and props).
3. Applies the hard gates, scores, ranks, and fills only the slots still open today.
4. Writes `YetAIBet` rows with `source='auto'`, `status='active'` and `prediction_factors.grading`.
5. Writes one `auto_pick_runs` row with drop-reason counts and the top rejected candidates.

A published pick is never edited or replaced by a later run.

## Flags

Beat runs inside the **celery-worker** service (`scripts/railway-celery.sh`, `worker --beat`); there is no
separate beat service. The worker reads every flag except the last row. The API reads only
`AUTO_YETAI_PICKS_ENABLED`, for the `/admin/pipelines` display.

| Flag | Default | Effect |
|---|---|---|
| `AUTO_YETAI_PICKS_ENABLED` | on (unset = on) | Registers the 11:00 and 17:30 runs and the pending-expiry job in beat. `false` / `0` / `no` / `off` is the kill switch: no new picks. Settlement is unaffected. |
| `AUTO_YETAI_PICKS_AUTO_PUBLISH` | `true` | `true`: picks go straight to `active`. `false`: legacy manual flow, picks are `pending_approval` until an admin approves them at `/admin/yetai-picks`. |
| `AUTO_YETAI_PICKS_MIN_SCORE` | `55` | Floor for fill-in picks when fewer than 2 clear `score_threshold`. A non-numeric value logs a warning and uses 55. |
| `AUTO_YETAI_PARLAY_ENABLED` | `false` | Also builds one 2-leg auto parlay (legs pass the same gates). |
| `YETAI_SETTLE_RETRY_DAYS` | `3` | Days a pick that cannot be graded is retried before it becomes `void` (anchored at the later of the game day and the first attempt day, so a game ESPN never lists voids about 4.5 days after it). Transport errors (ESPN down) void only after the 14-day backstop (`SETTLE_BACKSTOP_DAYS`). |
| `NEXT_PUBLIC_AUTO_YETAI_PICKS_ENABLED` (frontend) | `false` | Only hides a warning banner on `/admin/yetai-picks`; the page always renders. |

Changing a worker flag needs a celery-worker restart (beat reads env at import).

Tuning knobs live in the `scoring_config` row: `score_threshold` (default 65), `odds_min` / `odds_max`
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
- Ranked by score. Picks at or above `score_threshold` first; if the day would have fewer than 2, fill up to 2
  from candidates at or above `AUTO_YETAI_PICKS_MIN_SCORE`. Never below the floor: zero picks is a valid day.
- One pick per game per day (game = league + ET date + teams).
- Tiers by rank: rank 1 FREE, ranks 2-3 PRO.

### Hard gates (drop reason recorded on the run)

| Reason | Meaning |
|---|---|
| `no_play` | The model did not name a side. Sources also skip NO_PLAY / PASS rows outright. |
| `non_positive_edge` | Edge for the picked side is zero or negative. |
| `odds_out_of_bounds` | Price outside `odds_min` / `odds_max`. |
| `ungradeable` | `yetai_grading.can_grade(league, market, stat)` is false, so settlement could not grade it. |
| `started_or_starting` | Game started or starts within 20 minutes. |
| `start_time_unknown` | No start time and it is past 12:00 ET. |
| `injury_flag` | Source flagged the player/goalie (e.g. scratched). |
| `event_already_used` | A pick in this game was already published today. |
| `below_threshold` / `below_floor` / `cap_reached` / `same_event` / `market_concentration` | Ranking outcomes. |

### Score

Weighted sum of: edge for the picked side (spread: side-relative margin plus the side's spread; total and props:
signed by over/under; moneyline: model win prob minus the no-vig implied prob), historical hit rate of auto picks
per (market, league) over 90 days (neutral 50 until 20 graded picks), freshness (row timestamp age when the
table has one, sample size, injury), line movement (neutral, no snapshot table), odds sanity, model confidence.

The edge sub-score is `edge / scale * 100` (capped at 100), where the scale is "a strong edge is about this big"
for that market so scores compare across markets (`sub_scores.py`, one table): props per stat (points 4,
rebounds 2.5, assists 2, steals/blocks 0.8, threes 1.2, PRA 6, passing yards 40, receiving/rushing yards 18,
saves 4, shots on goal 1.5, strikeouts 1.5, hits 0.5; unknown stat = 15% of the line), spreads per league
(NBA/WNBA 7, NFL 4), totals per league (NBA/WNBA 8, NFL 5, NHL 1.0, MLB 1.5), moneyline 0.20 win probability.
These are hand-set; tune them from graded results.

Spread and total sources that price from the game-lines table (NBA, WNBA, NFL) handle a line that moved after
the projection ran: the edge is re-derived from the stored projected margin/total against the CURRENT line. The
candidate is kept only if the side is unchanged and the new edge still meets the projector's own play threshold
(NBA/WNBA spread 2.0, NFL spread 3.0, NBA totals `MIN_EDGE` 4.0, WNBA totals 2.0, NFL totals 3.0), and it is
published with the current line and price.

NBA / WNBA prop tables store the FanDuel price of the picked side in `fanduel_price` (written with the line by
`apply_fanduel_to_projection`, the PRA / threes generators and `etl/wnba/_prop_lines.py`). The prop sources publish
that real price; a row with no price (written before the column existed, or the book sent none) is skipped, and the
odds gate applies to props like every other market. If the migration `20261113_prop_fanduel_price` has not run, the
prop SELECT fails, is logged, and the prop source returns no rows.
Game-line markets without a stored price are skipped. The MLB hits board is
not a source (no market line or price stored). The NHL goalie-saves source is also not registered: its writer
needs boxscore starters, which do not exist pregame.

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
  It defaults `now` to 11:00 ET but runs with `reserve_slots=0`, so it shows evening / fire-now behaviour (up to
  3 picks plus floor fill), not the 11:00 reserve behaviour.

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
