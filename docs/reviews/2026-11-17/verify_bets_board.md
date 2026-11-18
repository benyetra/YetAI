# Verification of bets / board claims (adversarial pass, 2026-11-17)

Code read at the worktree (production 5b662edf). Functions run locally with no database:
`record_gate.combine`, `record_gate.fill_floor_edge`, `ConfidenceScorer.score` (backend venv, PYTHONPATH=backend).
Paths are relative to `backend/` unless they start with `frontend/`.

## 1. PRA has no record check: HOLDS (one small correction)
- `app/tasks/auto_pick.py:51` registers `PlayerPropSource`, and its spec list includes PRA at
  `app/services/auto_pick/sources/player_prop_source.py:29`.
- The gate's NBA prop loader map `_NBA_PROP_STATS` (`app/services/auto_pick/record_gate.py:249-255`) covers
  points, threes, steals, assists and rebounds. It has no `pra_ou`, even though `nba_accuracy_service.py:101`
  already builds a `pra_ou` bucket the loader could use. The comment at `record_gate.py:461-462` says this
  outright: "Keys without a projection record (bet record only): NBA moneyline / pra props".
- Prove-in default `record_gate.py:63` = `NHL,NBA/player_prop/steals,NBA/player_prop/blocks`. PRA is not in it.
- Correction: PRA is not checked "with no record at all". It has a bet-only record (`load_bet_records`, 4
  `sum-pra-v1` bets in 30 days per the 11-17 report). That record can never reach `min_picks` 30, so
  `combine` never sets withheld and `drop_reason` returns None. In practice that is no check.
- Points is withheld (11-17 report: `WITHHELD NBA/player_prop/points`).
- Projection: `etl/nba/generate_pra_predictions.py:173-205` is the sum of the stored points, rebounds and
  assists projections (`CORRELATION_ADJUSTMENT = 1.0`), clamped to [10, 80]. Rows below 15 are skipped. When
  a component row is missing, it falls back to a recency-weighted 10-game average (`_get_component`).

## 2. Scorer: HOLDS (I ran it)
Weights `scoring_context.py:7-13` (edge 0.40, historical 0.20, freshness 0.15, line_movement 0.10,
odds_sanity 0.10, model_conf 0.05). The DB row could override them (`config_loader.py:35-47`), but the
seed is the same (`alembic/versions/186bd4461744...py:207`). The live row is not knowable without the DB.

The real `ConfidenceScorer` on NBA PRA over candidates, other inputs neutral:
- **Price only** (gap 3.0): -150 / -130 / -110 / +100 / +150 all score **62.5**. -160 → 61.83, -200 → 59.17,
  -300 → 52.5. `odds_sanity_sub_score` (`sub_scores.py:161-167`) is flat 100 on [-150, +150].
- **Gap only** (-110): 0.5 → 45.83, 1.875 → 55.0 (fill floor), 3 → 62.5, 4.5 → 72.5, 6 → **82.5**. 8 and
  12 also give 82.5: the edge sub-score caps at gap = normalizer (PRA 6.0, points 4.0, `sub_scores.py:19-34,84-89`).
  Points with gap 4 and gap 10 both score 82.5.
- Nothing else varies between NBA prop candidates, so the reviewers' "dominated" holds:
  - line movement is always neutral (`context_builder.py:134-142` returns `{}`);
  - freshness is always 100 for props (`generated_at` None, `injury_flag` hard-coded False, `_basketball.py:257,263`);
  - historical is a per-stat constant.
- No shrinkage toward the line, and no EV or no-vig check, anywhere in `sub_scores.py`, `scorer.py` or
  `selector.py`. `hard_gate_reason` (`selector.py:59-80`) checks only that edge > 0 and that odds fall in
  [-300, +400].
- EV discarded: `odds_math.best_quote` (`app/services/odds_math.py:148-185`) computes `fair` and `ev` and ranks
  quotes by them. `apply_fanduel_to_projection` (`etl/nba/_fanduel_lines.py:390-398`) stores only book, line
  and price. Nothing rejects a negative EV, so the "best" quote can still be -EV.
- The only no-vig logic is in the NBA moneyline source (`sources/nba_moneyline_source.py:4`), as the
  moneyline edge input.

## 3. Record gate: PARTLY. The mechanics hold, but the ROI "reproduction" is circular.
- These hold, from `record_gate.py:55-61,172-202` and `accuracy_shared.py:516-533` (via `units_for_result`):
  - an unpriced row is valued at -110;
  - `n_eff = proj_n·min(1, 60/proj_n) + bet_n`, so it caps at 60 plus bets;
  - `shrunk = (units·scale + bet_units)/(n_eff + 20)`, which shrinks toward 0 ROI;
  - a key is withheld when n_eff ≥ 30 and shrunk < -2%. On a big sample that is a raw ROI below **-2.667%**
    (-0.02·80/60, which I computed).
  - The window is 90 days (`DEFAULT_WINDOW_DAYS`).
- "Not scoped by model_version" is PARTLY true:
  - NBA props, NFL and the bet record are not scoped.
  - NBA totals and spread ARE scoped to the current version (`version_pick_record`, `record_gate.py:337-354`).
  - NHL excludes pre-repair versions (`:360-373`).
- The 11-17 numbers, run through the real `combine`:
  - n_eff: threes **62.0** and points **61.0**. These match the report.
  - ROI with every row valued at -110: threes gives **-1.0% (open)** and points gives **-3.31%** (withheld).
    So the report's -3.6% for threes and -3.5% for points must come from stored prices.
  - Back-solved projection units: threes **-6.5u** (raw ROI -1.6% on 410 calls, even though it hits 53.4%)
    and points **-61.6u**.
  - The report never prints `proj_units`. bets.md calls this a reproduction, but it fed in the back-solved
    -6.5u, so the numbers are consistent, not independently reproduced.
- A market that hits 50% over 1,500 calls:
  - valued at -110: n_eff 60, shrunk **-3.41%**, withheld;
  - at a real -125: units -150, shrunk **-7.50%**, withheld.
  - Both are withheld, so this example does not show the hole.
- Where the hole actually is:
  - At -110 valuation a key stays open down to about a **51.0%** hit rate.
  - At a real -125, breakeven is 55.6%.
  - Real function at -125, 1,500 calls: 53% → -3.45% (withheld), 54% → -2.10% (withheld),
    54.5% → -1.42% (open). Every one of those loses money at -125.
  - If those rows are unpriced and valued at -110, a 53-54% market shows positive ROI and stays open.
- **Are rebounds and assists staying open explained? Not from the evidence.**
  - The gate section prints only withheld keys (`model_review_service.py:1257-1263`), so their n_eff and ROI
    do not exist in any report.
  - What we do know:
    - the gate filters calls to the fill-floor edge (assists 0.625, rebounds 0.781, computed with
      `fill_floor_edge`);
    - most rows are unpriced (30d priced: assists 252/1312, rebounds 323/1681);
    - the season audit has assists hitting 54.1% at |edge| ≥ 0.5 and rebounds 53.9%.
  - The -110 valuation is a plausible explanation. It stays a HYPOTHESIS until `python -m
    app.services.auto_pick` (dry-run `gate_report`) prints those rows.

## 4. What publishes with no record: PARTLY
Registered sources (`app/tasks/auto_pick.py:48-72`), and what the gate does with each:

| Sport | Source / key | What the gate does |
|---|---|---|
| NBA | points | loader; WITHHELD (losing) |
| NBA | threes | loader; WITHHELD (losing) |
| NBA | assists | loader; open |
| NBA | rebounds | loader; open |
| NBA | steals | loader + prove-in; withheld unproven (13/21 in 30d) |
| NBA | pra | **no loader, not prove-in: open** |
| NBA | spread | loader is version-scoped, 0/0 → n_eff 0 → the gate does not withhold. It is kept out only because the ETL writes NO_PLAY (`spread_rows` skips rows with no HOME/AWAY) |
| NBA | total | same as NBA spread |
| NBA | moneyline | **no loader: open** (1 bet) |
| NBA | blocks | not a source: no `fanduel_line` (`player_prop_source.py:31`) |
| NHL | saves, total | loader + prove-in (prefix "NHL"): withheld unproven |
| NFL | passing_yards, spread, total | loader; WITHHELD (losing) |
| NFL | receiving_yards | loader exists (`record_gate.py:443-448`) but has 0/0 graded calls, so it is **open with an empty record**. The claim says "no record check"; more precisely the check runs but has nothing to grade |
| MLB | strikeouts, moneyline | no loader, bet-only; off-season, no rows |
| WNBA | props, spread, total | no loader, bet-only; off-season, no rows |

- So the claim's list (PRA, NBA moneyline, NFL receiving yards) is right.
- It leaves out two things:
  - assists and rebounds publish today with a record, and that record is questionable (claim 3);
  - NBA spread and total would also pass the gate if the ETL ever writes a side.
- These hold:
  - The daily cap is 3: `config_loader.py:9,47`.
  - The cap per (league, market type) is 2: `selector.py:34,55-56`. All NBA prop stats share one key,
    `(NBA, player_prop)`.
  - The 11:00 run caps itself at 2 (reserve_slots=1, `orchestrator.py:334-335`, `celery_app.py:354-358`).
- "Exactly 2 NBA props a day" also depends on the fill-to-2 rule (`min_picks` 2, floor 55,
  `selector.py:31-32,135-137`). Picks can be fill picks scoring 55-65, not only picks above the 65 threshold.
  NBA moneyline or PRA would only add a third pick when nothing else takes the slot, and none has been seen.
- Env vars that would change this:
  - `AUTO_PICK_REQUIRE_PROVEN_RECORD` (default false)
  - `AUTO_PICK_PROVE_IN_KEYS`
  - `AUTO_PICK_RECORD_{MIN_PICKS,WINDOW_DAYS,MIN_ROI,PRIOR_MAX_PICKS,SHRINK_PICKS}`
  - `AUTO_PICK_RECORD_GATE_ENABLED`
  - `AUTO_YETAI_PICKS_MIN_SCORE`
- None of their production (Railway celery-worker) values can be known from the repo. The runbook
  (`docs/runbooks/auto-yetai-picks.md:40-45`) lists only defaults.
- Caveat: the Daily Model Review gate section runs in GitHub Actions, where none of these vars are set (the
  env block in the 11-17 log shows only RAILWAY_TOKEN, POSTGRES_SERVICE_ID and DEBUG). It therefore shows the
  gate at default settings, not necessarily what production uses.

## 5. Board surfaces: HOLDS, and the reviewers understated it
- **NBA API:** `/nba` (`app/api/v1/predictions.py:907-914`) calls `_withhold_unproven_picks` only with
  `_NBA_NEW_MARKET_KEYS` = steals and blocks (`:184-187`). Points, threes, assists, rebounds and PRA keep their
  `recommendation`, `fanduel_over_under`, `value_tier` and `pick_confidence`.
- **NBA "Best edges" (understated):**
  - The strip (`frontend/src/lib/propDiscoveryConfigs.ts:19-27`, `lib/propDiscovery.ts:67-78`) ranks rows by
    `edge`.
  - `edge = projected − fanduel_line` (`player_prop_projection_display.py:139`), and the withholding helper
    never clears it (`_NO_PICK`, `predictions.py:167-172,189`).
  - So **withheld steals rows still appear** in Best edges. The pick label shows "—", but the Gamble It
    button stays. `gamblyLegFromDiscoveryRow` (`frontend/src/lib/gambly.ts:148-152`) rebuilds the side from
    projection vs line when the pick is null.
  - Blocks never appears because it has no line.
  - The strip keeps only `edge > 0`, so it lists only overs. Under calls never appear there.
  - Gamble It renders only when `NEXT_PUBLIC_GAMBLY_ENABLED` is on (`GambleItButton.tsx:29`). Its production
    (Vercel) value is not in the repo.
- **NBA prop tables:** show the pick for points, threes, assists, rebounds and PRA; steals and blocks are
  stripped.
- **NBA game cards:** spread and total recommendations come from the ETL, which writes NO_PLAY for the
  unproven anchored versions. `spreadRecommendation` (`frontend/src/components/yetai/MlbGameProjectionsGrid.tsx:126-139`)
  re-derives a side at |margin − market| ≥ **2.0** for NBA and WNBA (`:60-72`). With the anchor's k near 0
  that rarely fires. Totals are not re-derived.
- **NFL API:** `/nfl` (`predictions.py:918-988`) never calls the helper. QB passing, receiving yards and
  anytime-TD rows keep their picks, and so do spread and total. On the game cards the frontend re-derives a
  spread side at |edge| ≥ **3.0** (`MlbGameProjectionsGrid.tsx:80-84,126-139`), but only when the stored
  recommendation is not HOME/AWAY. "Regardless of the backend" is accurate only in that sense: the frontend
  replaces a missing pick, it does not override a stored one. The NFL page has no Best edges strip.
- **NHL:** `/nhl` withholds goalie saves, shots and team totals through the gate (`predictions.py:1072-1075`;
  prove-in, so all withheld). The frontend reads totals from `betting_recommendation`
  (`frontend/src/lib/mapNhlGameProjections.ts:31`), which is stripped. No NHL pick labels show. There is no
  Best edges strip.

## 6. Timing and inputs: PARTLY
- These hold:
  - Auto picks run at 11:00 ET (`celery_app.py:354-358`) and 17:30 ET (`EVENING_RUN_ET`,
    `auto_pick/candidate.py:10`). The Celery timezone is America/New_York (`celery_app.py:43`).
  - The NBA pipeline runs at 03:30 (`:115-116`).
  - The pregame refresh runs at 12:00 and 17:00 (`:119-120`).
  - The 11:00 run therefore uses 03:30 rows.
- **Wrong: "refreshes do not re-project".** `NBA_PREGAME_PHASES` (`app/tasks/etl_pipeline.py:547-559`) re-runs
  injury status, expected minutes and game lines, then **the whole predictions phase** (every prop generator,
  PRA, totals and spread). What actually happens is that it re-projects but the inputs barely change.
  `NBA_PREGAME_REFRESH_ENABLED` can disable it (default on; production value not knowable).
- No line-freshness penalty: holds.
  - The NBA prop specs pass `generated_at` None (`player_prop_source.py:24-29`, `_basketball.py:257`), so
    `freshness_sub_score` never ages them.
  - `injury_flag` is hard-coded False (`_basketball.py:263`).
  - A `projected_at` stamp does exist (`_fanduel_lines.py:363`) and goes unused.
- Inputs: PARTLY.
  - No generator reads the expected-minutes table. `PlayerExpectedMinutes` is written by
    `update_expected_minutes.py` and read nowhere else in `app/`.
  - No prop projection adjusts for teammates being out.
  - Two injury effects do exist:
    - each prop generator skips or flags as OUT a player whose own status is out, ir or doubtful
      (`generate_points_predictions.py:41-48`, `generate_pra_predictions.py:137-145`);
    - the totals projector drops OUT/IR players from team rosters (`totals_projector.py:250-257`).
  - The features use past minutes (rolling 3, 5, 10 and 20 games, `_feature_engineering.py:129-156,300-306`),
    not expected minutes.

## 7. Odds, stake and settlement: PARTLY
- Odds: the bet stores `c.market_odds` (`orchestrator.py:804`), which is the row's `best_price`
  (`_basketball.py:225-227`). That is the best-EV quote across books at the row's last fetch: 03:30 for the
  11:00 run, the 17:00 refresh for the 17:30 run. If a refresh finds nothing, the old line and best price are
  kept (`_fanduel_lines.py:370-381`).
- Stake: every unit figure is flat 1u (`record_gate.stake_units`). There is no stake field in the auto build.
- Settlement:
  - Pushes settle as **`pushed`, not `void`** (`yetai_grading.py:414,629`). Either way they are not a loss
    and are excluded from the record, which counts only won and lost (`record_gate.py:214`).
  - DNP → void (`yetai_grading.py:584-585`).
  - Player not in the box score (unmatched name) → `not_ready`, retried, then **void** once the window or
    backstop passes (`yetai_bets_service_db.py:1415-1418`).
  - Ambiguous name or stat not recorded → `ungradeable` → void (`:1419-1420`).
