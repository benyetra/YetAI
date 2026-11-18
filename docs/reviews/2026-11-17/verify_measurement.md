# Verification of measurement/infra claims (adversarial pass, 2026-11-17)

Read-only. No DB. Local runs used `/Users/byetz/Development/YetAI/YetAI/backend/.venv/bin/python` with
PYTHONPATH=backend of this worktree. Evidence refs: R14..R17 = `evidence/daily_review_2026-11-1x.txt`.

## 1. Fair-price shadow interval and rule: PARTLY (the interval and error-rate parts hold; the vig reason is WRONG)
- **Interval, HOLDS.** `fair_price/backtest.py:179-192` `clustered_mean` returns no interval when G<2. R16:307
  shows n=8 with no interval, so all 8 flags were on one date. R17:307 shows n=85 with an interval, so the flags
  span 2 dates (8 and 77). I re-ran `clustered_mean` with an 8-flag date at -0.8 and a 77-flag date at -1.131
  (mean -1.1). Result: se 0.056, interval [-1.211, -0.989], which matches the printed [-1.2, -1.0]. The result is
  the same whether the spread within a date is 0 or 5 points. With G=2 the se depends only on how far apart the
  two daily means are. The doc's own power table assumes a per-flag SD of 5.1-5.4 points
  (`docs/fair-price-shadow-decision.md`, "Power, honestly"). That implies about ±1.1 at n=85, against the ±0.11
  printed.
- **Rule.** `decide` (`backtest.py:246-268`) applies to the first 300 primary flags (`MIN_N_GO=300`, :27):
  - INVALID: the placebo fails, or the random baseline's CLV lower bound is above 0.
  - GO: CLV lower bound > 0, ROI ≥ 0 and the paired (flag − random) CLV lower bound > 0.
  - NO GO: CLV upper bound ≤ 0. The ROI arm (`roi_hi<0`) needs n≥1000 (`MIN_N_ROI_NO_GO`, :28).
  - Every bound is mean ± 1.96·CR-se clustered by game date. Nothing in the rule requires a minimum number of
    dates.
- **Dates at 300, HOLDS (roughly).** 89 primary flags came on 11-16 alone (R17:304). About 215 more are needed,
  so 300 arrives in about 3 more slates, on about 5 dates.
- **Error rate, fair but size it.** Simulation with the repo function: true CLV 0, per-flag SD 5, 300 flags, and
  date effects of 0 or 1.0. The one-sided NO-GO false alarm is 7.2% with 4 dates, 6.0-6.3% with 5 and 2.5-2.9%
  with 30, against a nominal 2.5%. That is about 2.5-3x the nominal rate, not 10x. The GO side is less inflated
  because it needs 3 conditions at once. The real problem is that G-1≈4 degrees of freedom are read with z=1.96
  instead of t₄=2.78.
- **"Not a vig artifact because it compares no-vig to no-vig", WRONG.** `fair_price/grade.py:88` computes
  `clv = p_close − american_to_prob(f.price)`. `odds_math.py:56-58` says that is the implied probability "vig
  included". The comparison is no-vig close against the with-vig price, the same definition as the backtest.
  The conclusion still holds: a flag needs EV ≥ 5% against the leave-one-out fair, so at flag time fair − implied
  is already ≥ about +2.4pt near even money. A CLV of -1.1 therefore means the fair consensus moved about 3.5pt or
  more against the flag. Vig is the reason the rule pairs every flag with a random baseline.
- **Repeat snapshots, the claim's worry is WRONG.** There is one row per (rule, event, market, player_key,
  side, book): see `shadow.py:106-130` (a later sighting only bumps `last_qualified_at` and `n_qualified`) and
  the unique constraint at `predictions_models.py:4033-4042`. The same player and side at *different books* are
  still separate, correlated flags. That is a real dependence the date clustering only partly absorbs.

## 2. NBA prop "prob CLV": HOLDS
- `prop_clv.py:57-60` calls `odds_math.prob_clv` (`odds_math.py:194-207`), which is the no-vig consensus at the
  taken line minus `american_to_prob(taken_price)` (with vig). A zero-skill call at -110 scores about -2.4pt; the
  range is about -1.2 at -105 and -3.5 at -115/-115.
- Nuance: the score is computed for every graded projection call, not only YetAI picks
  (`model_review_service.py:822-875`). It uses the stored best-book quote when present, which makes the vig drag
  smaller.
- Close capture: `etl/nba/close_capture.py:55-56` defaults to `player_rebounds,player_assists`. It can be
  overridden by an env var I cannot see, but the data shows it is not overridden. Beat: `celery_app.py:126-130`
  (every 10 min, 11-23 ET); pregame refreshes are at 12:00 and 17:00 (:119-123). The close is the latest
  snapshot first seen before the start (`odds_snapshots.py:282-298`).
- R17:290-294: points, threes and steals close a median 142, 138 and 154 min before the start, with line CLV
  mean and median exactly 0.00. Rebounds and assists close 20 min before. So the "close" for points, threes and
  steals is the 17:00 fetch the price came from. Their prob CLV (-1.7, -2.0, -2.5) is pure vig.

## 3. NBA weekly retrain: HOLDS on (a)-(d), with one addition
- **(a) HOLDS for the props trainer.** The only promote check is `upload_gated(candidate_metric=validation["mae"],
  score_champion=live_scorer(...))` (`ml_training/run_train_props.py:262-279`). The line comparison is passed
  only as `manifest_extra`, and its docstring says "Reported only" (:68-70).
  - Spread does have a beat-the-market gate: `below_baseline` (log: "does not beat the market line").
  - The residual models have `beats_line_gate` (`residual/train.py:115`).
- **(b) HOLDS.** `residual/dataset.py:19-22,31` define `PROJECTION_TABLE` and `PROJECTION_COLUMN` for rebounds and
  assists only. The points manifest in `retrain_43952830509.log:252482,252490` shows `line_mae: null` and
  `side_hit_rate: null`.
- **(c) HOLDS.** Rebounds on 11-16: candidate 1.907597 against champion 1.907761, an improvement of 0.00016, and
  it was "uploaded". Its `line_comparison` (log:758241-758256): n 1339, model_mae 2.0335, line_mae 1.9586,
  beats_line false, side_hit_rate 0.5019.
- **(d) HOLDS.** The step runs under `shell: /usr/bin/bash -e {0}` (log:91), and the script adds
  `set -uo pipefail`, so `python … | tee` returns 1 and `-e` exits before the grep. `ml_training/__main__.py:57-60`
  returns 1 for any status except ok or dry_run.
  - In `.failed.log`, points (:252915→:253240) and assists (:506963→:507288) end with "exit code 1" and no
    `::warning::` line.
  - Spread's ordinary `below_baseline` turns red the same way, on both 11-14 and 11-16.
  - Because of `fail-fast: false`, rebounds and both residual jobs still ran (11-16 run).

## 4. Daily-review MAE against line MAE on different rows: HOLDS
- `model_review_service.py:418-431`: `mae` is computed over every scored row, while `line_mae` is computed only
  over rows with a line. The printed `(n=…)` is the all-rows count. R17:215: "MAE 1.39, line MAE 1.71 (n=3124)".
- The audit on the same lined rows (R17:141-142) gives line 1.71 against projection 1.76, so the projection is
  worse. The audit window is 400 days (`scripts/nba_props_audit.py:168`) and the review's is 30
  (`MODEL_WINDOW_DAYS=30`). The samples are close but not identical; the direction of the bias in the review is
  confirmed.

## 5. Stored side against projection-vs-line: HOLDS
- The review grades `fanduel_over_under`, the stored side (`model_review_service.py:135`, `:395-405`). The audit
  grades `(proj>line)==(actual>line)` (`scripts/nba_props_audit.py:39-49`).
- #170 (986d309f, 11-10) changed the side rule. The register's NBA-11 says the old rows were wrong on 21-54% and
  were never recomputed.
- The newest days agree:

  | Market | Interval | Review (stored side) | Audit (projection vs line) |
  |---|---|---|---|
  | Rebounds | 15→16 | 55/98 | 98 picks, ≈56 hits |
  | Rebounds | 16→17 | 44/87 | 87 picks, ≈44 hits |
  | Assists | 15→16 | 39/81 | 81 picks, ≈39 hits |
  | Assists | 16→17 | 35/72 | 72 picks, ≈34 hits |

  The counts match exactly and the hits match within rounding. So the 49.1% against 52.2% gap comes from old rows
  (plus the 30-day against 400-day window).

## 6. NFL receiving yards: HOLDS (small wording fix)
- `collect_recv_yds_actuals.py:104-105` grades `get_current_nfl_week() − 1` only. Running `get_current_nfl_week`
  locally (first Thursday 2026-09-10) gives week 9 for 11-09 to 11-11 and week 10 for 11-12 to 11-18. Week 10 was
  played 11-12 to 11-16, and the grader moves to week 10 on Thu 11-19.
- The grader runs daily inside the 04:30 NFL pipeline (`etl_pipeline.py:813-823`), so "next weekly run" should
  read "first daily run on or after 11-19".
- v1 at 0da1eb97: `recv_yds_usage.py:160` labelled rows with `get_current_nfl_week()`, which was 9 on Tue 11-10,
  and took lines from the Odds feed, which was by then showing week 10 games. The n=21 graded rows can only be
  those, because v2 is week 10 and still ungraded. Confirmed by elimination, not by a row-level query.

## 7. NFL anytime TD: HOLDS
- It is graded: `nfl_anytime_td_actuals` runs in `NFL_PHASES` (`etl_pipeline.py:817-822`).
- It is absent from the review's loaders (`model_review_service.py:340-364`; `_nfl` returns passing, receiving,
  spread and total) and from `record_gate.py` (grep finds no "anytime").
- Calls: OVER, or UNDER ("No TD") when edge ≤ -0.05, with no price or EV check on that side
  (`anytime_td_market_anchor.py:133-144`).
- QB prior: rz share 0.07 × conversion 0.14 (`anytime_td_features.py:40-51`). That is about 1% per team red-zone
  trip, or about 3% λ at 3.2 trips. The backtest's own QB prior is 0.12 (`anytime_td_backtest.py:23-24`).
- Freeze is by date: `_is_played` is `game_date < today` (`anytime_td_projector.py:158-162,276-289`), and
  betting uses `game_day < today` (`anytime_td_betting.py:477-480`).
- The Sunday 10:00, 12:30 and 15:30 gameday runs include the ATD projector and betting
  (`etl_pipeline.py:872-895`), so rows for 13:00 games are rewritten at 15:30.

## 8. NFL spread and QB ML: PARTLY
- **Spread, HOLDS in substance.**
  - `NFL_CONFIG = SpreadLeagueConfig(home_court_advantage=2.5, edge_threshold=3.0)` (`_spread_model.py:33`).
    Everything else is the basketball default: elo_k 20, spread_per_elo 25, logistic scale 7, pace overlay 0.15,
    `season_start_month=5`.
  - The margin is Elo + PPG overlay + QB-out with no market term (`nfl/spread_projector.py:108-126`). The market
    spread is used only for `spread_recommendation`, so it is unanchored and emits HOME/AWAY calls.
  - Overstated: 2.5 is set explicitly and is not an absurd NFL home edge (modern estimates are about 1.5-2). The
    clearly wrong inherited parts are the May season start and the basketball Elo scale.
- **QB ML, code HOLDS; "every row is PASS" is not verifiable here.**
  - With the flag on and a real line, the GBM output is published as it is (`qb_passing_yards_ml.py:304-305`).
  - The model is a market-baseline residual model, optionally blended with the line (:972-990).
  - A call needs |edge| ≥ 7% (`qb_betting.py:132,152-161`).
  - The review still shows 6/18 calls in 30 days (R17:224). "Every row PASS" therefore applies to the post-11-10
    model only; that comes from the reviewer's week-10 count, which I cannot reproduce without the DB.

## 9. NHL: HOLDS
- **Saves join.** The label is `p.goalie_name` (`model_review_service.py:257-258`), which comes from `db_row.name`
  (`confirm_starters.py:259`). `NHLGoalie.name` is the boxscore `name.default`
  (`collect_historical_data.py:253,406-409`). Locally `player_key('J. Swayman')` gives 'j swayman' and
  `player_key('Jeremy Swayman')` gives 'jeremy swayman', so the two can never match. R17:295 shows "13 calls, 0
  with a close".
- **Shots.** There is no shots key in `_nhl` (:278-281), and `_CLV_UNJOINED` says so (:816-819).
- **Week of games.** `_run_daily_core` takes every game in `schedule["gameWeek"]` (`daily_predictions.py:665-667`),
  and NHL `/schedule/{date}` returns 7 days. The comment at `generate_daily_predictions.py:172-173` is wrong. The
  credit cost is CODE-ONLY.

## 10. Redelivery and the 17:30 overlap: PARTLY
- **Redelivery, HOLDS, with one nuance.** `task_acks_late=True` and `visibility_timeout=86400`
  (`celery_app.py:46-52`).
  - These beat entries have no `expires`: `nba-update-pipeline-daily`, `nfl-update-pipeline-daily`,
    `nhl-update-pipeline-daily`, `nba-spreads-accuracy-morning` and the midweek ATD run (`celery_app.py:114-117,
    159-162, 211-214, 215-218, 207-210`).
  - The auto-pick entries carry `expires` for exactly this reason (comment at :358).
  - Nuance: redelivery needs the whole worker to die (deploy, container kill) with the message unacked. A pool
    child that crashes inside a live worker is acked as failed, because `task_reject_on_worker_lost` is left at
    its default False.
- **17:30 half-finished refresh, CODE-ONLY / conditional.**
  - `auto_pick.yetai_bets` runs on its own queue (`celery_app.py:68-86`). The 17:00 refresh is on the default
    queue.
  - The only lock serialises auto-pick runs (`orchestrator.py:126-130`). No refresh-completion check exists.
  - It happens only if `CELERY_ROLE=etl` (runbook Step 4) is live and the 17:00 refresh runs longer than 30 min.
    Neither is visible in the evidence.
