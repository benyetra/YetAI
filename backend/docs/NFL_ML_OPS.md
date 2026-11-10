# NFL ML operations

## Data source and the frozen week (all NFL boards)

- **nflverse weekly stats.** `nflverse_weekly.load_weekly_frame` tries the
  legacy `player_stats_{season}` file, then `stats_player_week_{season}`
  (nflverse stopped publishing the legacy file after 2024). Before this, every
  2025+ caller of `import_weekly_data` got a 404 and fell back to defaults:
  the QB "dynamic" tier was the static name table, and the shadow GBM saw
  tier-filled form features it was never trained on.
- **A kicked-off game is final.** The pipeline runs daily and
  `get_current_nfl_week` rolls over on Thursday, so Monday-Wednesday runs
  still name the week just played while the odds feed only lists next week.
  `nfl_common.has_kicked_off` gates QB (`qb_dynamic`, `qb_betting`), receiving
  yards (schedule filter), anytime TD (projector + betting) and kickers (next
  game only): rows keep the numbers, closing line and pick they had at
  kickoff. Without it, next week's line was written onto last week's row and
  graded as its O/U. Runs with an explicit `week=` are not frozen.
- **Lines.** `prop_lines.best_lines`: the line the edge is measured against is
  the middle book's (`consensus`); `best_over_book` is the lowest line,
  `best_under_book` the highest. Names match on `player_names.player_name_key`
  (punctuation, accents and Jr./III ignored), never by substring.

## Receiving yards (v2)

Non-ML: `expected targets × yards per target`, then soft-anchor publish
`α·model + (1−α)·line` with `NFL_RECV_ANCHOR_ALPHA` (default **0.25**). Lined
RB/WR/TE only; fail-closed Odds attach. **No** residual ML — do not set
`NFL_RECV_ML_ENABLED` (flag does not exist yet).

`recv_yds_usage` builds the inputs from each player's game log, this season
plus last season at 0.35 weight, with a 6-game recency half-life:

| Input | How |
|-------|-----|
| `target_share` | weighted targets / weighted team pass attempts |
| `team_pass_attempts` | team's last 6 games, blended with 3 league-average games (32.5) |
| `yards_per_target` | weighted yards / targets, shrunk toward the position average (WR 8.0, TE 7.3, RB 5.9) with 40 pseudo-targets |

v1 read all three from the single most recent game and multiplied targets by
yards per **reception** (every incompletion counted as a catch). Walk-forward
on nflverse 2025 + 2026 weeks 2-18, players averaging 4+ targets (3+ for RBs),
2,641 player-games:

| Model | 2025 MAE | 2026 MAE | Bias |
|-------|---------:|---------:|-----:|
| v1 (last game, targets × YPR) | 43.2 | 44.6 | +28 |
| Season average yards | 24.8 | 26.8 | +2 to +3 |
| **v2** | **23.4** | **24.2** | +1 to +2 |

There are no historical reception-yards lines in the repo, so this is error
against actual yards, not a line-vs-model result. Opponent and game date come
from this week's nflverse schedule (v1 showed last week's opponent).
Confidence is sample-based (0.50 + 0.045 per current-season game, capped at
five games), so picks need five games in the current role.

## QB passing yards (Phase 4.3+)

| Mode | Env | Production yards | `model_version` / `prediction_method` |
|------|-----|------------------|----------------------------------------|
| Soft-anchor (default) | `NFL_QB_ANCHOR_ALPHA` (default `0.25`) | When a real line is attached: `α·model + (1−α)·line` where model = `ml_shadow_yards` else tier; else dynamic tier | `soft_anchor` or `tier-v3` |
| ML shadow | — | Soft-anchor publish; GBM stored as `ml_shadow_yards` | `soft_anchor` / `tier-v3`; `feature_importance.ml_shadow_yards` |
| ML promote | `NFL_QB_ML_ENABLED=1` | Residual GBM when `line_is_real`; else soft-anchor / tier | `gbm-qb-residual-YYYYMMDD` |

**Dynamic tier:** `qb_features.dynamic_tier_from_history` shrinks the name
table toward the QB's own starts: `(4·tier + Σ w·yards) / (4 + Σ w)` over his
last 17 starts (15+ attempts; this season w = 1, last season w = 0.3), times a
quarter of the opponent's pass-yards-allowed gap to the league. Walk-forward on
nflverse starters, static table → old 60/40 last-5 blend → this:
2025 **59.4 → 58.6 → 56.5** MAE, 2026 (weeks 1-9) **59.0 → 58.2 → 56.7**, bias
+9.5 → +7.7 → +4.1 yards. Against the committed 2025 lines the tier alone still
loses to the line (55.5 vs 53.5 MAE) and its edge has no measurable signal,
which is why the publish stays soft-anchored at α = 0.25. The table's tiers
were calibrated in Aug 2026, so the 2025 numbers flatter the static tier. Both
dataset builders use the same function; re-run **NFL Prod QB Eval** before
relying on a model trained with the old 60/40 tier as its baseline.

**Tier v3:** No hash-based week noise. Uncertainty is
`prediction_interval_lower/upper` + confidence. Opt-in legacy noise with
`NFL_QB_TIER_HASH_VARIANCE=1`. Questionable starters: −12 yards + confidence hit
(Out/IR/Doubtful still promote backup).

**Late availability:** Beat jobs
`nfl-gameday-availability-{sun-am,sun-mid,sun-pm,mon,thu-am,thu-pm,sat}` re-run
QB + kickers near kickoff (then spread/totals + ATD). Within 3h of KO,
Questionable escalates to Out (backup promotion).
Within 12h, Q risk/yard cuts escalate; live backups take an extra −20 yards
(`NFL_QB_LATE_AVAILABILITY=0` to disable).

**Features:** form + volume + defense + weather + game market
(`total_line` / `spread_line` / `implied_team_total`) + scheme tags + prop-line
columns (`pass_yds_line`, `line_minus_tier`, `line_is_real`,
`market_residual_l3`, `line_minus_rolling`). **Promote residual path is v6
market residual**: baseline = `0.5*(tier+line)` when a real prop line is
present, full `FEATURE_NAMES`, HP sweep + `fit_full`. With 2025 Odds lines
committed into `models/nfl/pass_yds_lines.json` (Railway run 31552960099),
v6 cleared **+11.7%** vs dynamic tier on season_2025 holdout (v5 **+11.3%**).
Earlier tier-only + post-hoc line blend peaked ~**+7.5%** and remains an
ablation arm only — post-hoc `line_blend_w` is **not** applied to the market
promote gate (would dilute toward the line). Live `qb_betting` still reinjects
`pass_yds_line` for O/U / shadow context.

**Production ML gating:** with `NFL_QB_ML_ENABLED=1`, published yards use the
GBM only when a **real** prop line is on the feature row (`line_is_real`).
`qb_dynamic` runs before odds attach — without this gate, market-residual ML
without lines inverts the slate (mid-tier QBs above Allen/Mahomes). After
`qb_betting` reinjects lines, ML applies. Promote bundle loads from **S3**
(when ML is on); shipped `backend/models/nfl/` pickles are shadow-only.
When `NFL_QB_ML_ENABLED` is unset, a real `pass_yds_line` is **soft-anchored**
into `predicted_passing_yards` (`prediction_method=soft_anchor`):
`α·model + (1−α)·line` with `α = NFL_QB_ANCHOR_ALPHA` (default `0.25`) and
model = shadow GBM else tier. Edge = publish − line (UI: Model / Market /
Edge / Pick). Do **not** publish the raw market as the projection. GBM as the
sole published yards still requires the promote flag.

**O/U classifier:** trains on **real market lines only** (no synthetic tier±noise).
`qb_betting` blends yards-edge with `P(over)`; disagreement → always PASS.
ML PASS unless `|P(over)−0.5| ≥ 10%`; yards min edge 7%, min confidence 70%.

Promotion gate: residual ML MAE ≥ **10%** better than **dynamic tier** on
holdout **and** strictly better MAE than the published **market line**
(`line_only` / `line_mae`). After P0, production yards *are* the prop line when
ML is off — beating the stale tier table is not enough to flip
`NFL_QB_ML_ENABLED`. `nfl_prod_qb_eval.py` reports `mae_lift` (vs tier) and
`mae_lift_vs_line`. Upload S3 artifacts from a promote-gated eval (`--upload`),
then set `NFL_QB_ML_ENABLED=1` on Railway. Do not flip the flag before S3 has
the matching `market_residual_v6` bundle.

Prod eval (`scripts/nfl_prod_qb_eval.py` + workflow **NFL Prod QB Eval
(Railway)**):
- Promote model = **v6 market residual** + HP sweep (`default` / `shallow` /
  `strong_reg`) + **`fit_full=True`** (`n_train == rows_train`).
- Gate MAE is **raw** residual ML (no post-hoc line blend). Blend grid stays
  diagnostic in `ablations.line_blend_w_*`.
- Report includes **`ablations`** (v5/v6 market, tier-only HP variants, promote
  sweep) and `promote_hp_selected`.

### Latest Railway promote-gate (2026-09-04, run 33913715865) — line-vs-ML

| Metric | Value |
|--------|-------|
| Holdout | season_2025 (585); real lines **~91%** (`pass_yds_line_real_rate=0.9112`) |
| Promote path | **`market_residual_v6`** + HP `strong_reg` (raw ML; no line blend) |
| Dynamic-tier MAE | **65.525** |
| Residual ML MAE | **57.314** |
| Line-only MAE | **61.727** |
| Lift vs dynamic | **+12.53%** (≥10% gate) |
| Lift vs line | **+7.15%** (ML strictly better than line) |
| `promote_recommended` | **true** (tier lift **and** beats line) |
| S3 upload | **yes** — `s3://yetibets/nfl/ml_models/qb_passing_yards{,_metadata}.json` + O/U pair |
| Recommendation | Enable `NFL_QB_ML_ENABLED=1` on Railway after confirming S3 bundle |
| Ops note | Soft-anchor (#162) stays the default publish path until the flag is set. Agent cannot flip Railway vars without auth. |

### Prior Railway promote-gate (2026-08-12, run 31555122122)

| Metric | Value |
|--------|-------|
| Holdout | season_2025 (585); real lines **533/585 (91.1%)** |
| Index | committed `pass_yds_lines.json` **1628** (backfill skipped) |
| Dynamic-tier MAE | **65.5** |
| Promote path | **`market_residual_v6`** + HP `strong_reg` (raw ML; no line blend) |
| Residual ML MAE | **57.31** |
| Lift vs dynamic | **+12.53%** (then-gate ≥10% vs **tier only**) |
| Lift vs static | **+14.13%** |
| v5 / v6 ablations | +11.27% / +11.74% |
| `promote_recommended` (old gate) | **true** (tier lift only; no `line_mae`) |
| Next (done 2026-09-04) | Re-ran under line-vs-ML gate — see latest section. |

### Prior Railway ablations (2026-08-12, pre-promote-path switch)

| Metric | Value |
|--------|-------|
| Holdout | season_2025 (585); real lines **533/585 (91.1%)** |
| Index | `pass_yds_lines.json` **1628** lines (2023:556, 2024:537, **2025:535**) |
| Odds backfill | **2777** credits; `lines_added=535` |
| Dynamic-tier MAE | **65.5** |
| v5 market residual | **58.14** (**+11.27%**) |
| v6 market residual | **57.84** (**+11.74%**) |
| Tier-only + blend w=0.25 | 60.58 (+7.55%) — ablation only |
| Promote path (then) | still tier-only wire-up → switched in #103 |

### Prior Railway promote-gate (2026-08-12, tier-only + line blend, thin 2025 lines)

| Metric | Value |
|--------|-------|
| Holdout | season_2025 (585); real lines n=386 |
| Dynamic-tier MAE | **65.5** |
| Tier-only residual (`shallow`) | 63.4 (**+3.25%**) |
| Line blend grid (lift) | w=0 → **+7.42%**; w=0.25 → +6.85%; w=0.5 → +5.94%; w=0.75 → +4.76%; w=1 → +3.25% |
| Diagnostic best | **w=0** (pure line when present + ML else) → MAE 60.7 |
| Promote wire-up | **w≥0.25 only** (w=0 is market, not ML) |
| Gap to 10% gate | ~1.7 yards at w=0; ~2.1 yards at w=0.25 |
| Promote | **No** — keep `NFL_QB_ML_ENABLED` unset |

### Prior Railway ablations (2026-08-11, post-#98)

| Arm | MAE | Lift vs dynamic tier |
|-----|----:|---------------------:|
| Dynamic tier | 65.5 | — |
| Line-only (real rows) | 54.8 | — |
| v5 market residual | 67.0 | −2.3% |
| v6 market residual | 72.6 | −10.8% |
| Tier-only residual | **63.5** | **+3.0%** |
| Promote | **No** — keep ML shadow-only; next = tier-only + regularize |

### Prior Railway promote-gate (2026-08-11, v5 lift levers)

| Metric | Value |
|--------|-------|
| Rows | 1756 (2023–2025 actuals) |
| Holdout | season_2025 (585) |
| Real prop-line rate | 82.7% |
| Dynamic-tier MAE | **65.5** |
| Static-tier MAE | 66.7 |
| Residual ML MAE | **65.0** |
| Lift vs dynamic | **+0.9%** (need ≥10%) |
| Lift vs static | +2.7% |
| Promote | **No** — keep ML shadow-only |

### Offline nflverse retrain (2026-08-11, v6 features)

| Metric | Value |
|--------|-------|
| Holdout | time 20% |
| Tier MAE | **61.8** |
| Residual ML MAE | **62.7** |
| Lift | **−1.4%** (still below gate) |
| O/U (real lines only) | acc **0.55**, brier **0.248**, n=855 |
| Promote | **No** — keep `NFL_QB_ML_ENABLED` unset/0 |

### Prior offline retrain (2026-08-11, residual GBM, nflverse 2023–2025)

| Metric | Value |
|--------|-------|
| Rows | 1140 |
| Holdout | time 20% |
| Tier MAE | **61.8** |
| Residual ML MAE | **61.7** |
| Lift | **+0.2%** (far below 10% gate) |
| Promote? | **No** — keep `NFL_QB_ML_ENABLED` unset/0 |

### Prod DB retrain (2026-08-11, `pred_qb_actuals` 2025 W3–18)

| Metric | Value |
|--------|-------|
| Rows | 360 (train 288 / holdout 72) |
| Holdout | time 20% |
| Tier MAE | **72.8** |
| Residual ML MAE | **69.1** |
| Lift | **+5.1%** (below 10% gate) |
| Promote? | **No** |

### Actuals backfill + multi-season re-eval (2026-08-11)

| Metric | Value |
|--------|-------|
| Rows | **1756** (train 1171 / holdout 585 = season 2025) |
| Real pass-yds lines | **1453 / 1756 (82.7%)** after Odds historical backfill |
| Tier MAE | **66.7** |
| Residual ML MAE | **71.4** |
| Lift | **−7.0%** (ML worse than tier on 2025 holdout) |
| Promote? | **No** |
| Kicker FG MAE | **0.98** on **479** `pred_kicker_actuals` rows |
| Blend pin | `NFL_KICKER_BLEND_TUNED_WEIGHT=0.5` (CSV walk-forward) |

```bash
export DATABASE_URL=...   # Railway Postgres
export ODDS_API_KEY=...   # paid plan
cd backend
PYTHONPATH=. python scripts/nfl_backfill_actuals.py --kickers --season 2025
PYTHONPATH=. python scripts/nfl_backfill_actuals.py --qb --seasons 2023,2024,2025
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --seasons 2023,2024 --max-credits 5600
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --assign-teams --seasons 2023,2024
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py
PYTHONPATH=. python scripts/nfl_backtest.py --season 2025 --start-week 1 --end-week 18 --json
PYTHONPATH=. python scripts/nfl_tune_kicker_blend.py --write
```

GitHub Actions (preferred when local `.env.production` is a placeholder):

```bash
gh workflow run nfl-prod-qb-eval.yml -f season_start=2023-09-01 -f season_end=2026-02-15 -f force_upload=true
```

**Do not enable `NFL_QB_ML_ENABLED=1` unless holdout lift ≥10% vs dynamic
tier *and* ML MAE beats `line_only`.** Real pass-yards
prop lines come from `pred_qb_predictions.ou_line` and the historical Odds API
index (`models/nfl/pass_yds_lines.json`).

### Historical pass-yards props (Odds API)

Paid plan. Measured costs: **1 credit / gameday** (events slate) +
**10 credits / game** (`player_pass_yds`, `regions=us`). Responses cache in
`scripts/nfl_odds_cache.db` (gitignored `*.db`); derived lines land in
`models/nfl/pass_yds_lines.json`.

2023–25 REG: **1628** QB lines in committed `models/nfl/pass_yds_lines.json`
(2023:556, 2024:537, **2025:535**). 2025 backfill (Actions run 31552960099)
spent **2777** credits once; re-runs that hit the committed index / SQLite
cost **0**. Season_2025 holdout real-line coverage: **533/585 (91%)**.

```bash
export ODDS_API_KEY=...
cd backend
# Prefer committed index; only backfill when seasons are missing:
PYTHONPATH=. python scripts/nfl_pass_yds_line_coverage.py \
  --season-start 2025-09-01 --season-end 2026-02-15
# Optional refresh (paid Odds credits via Actions):
#   NFL Prod QB Eval → backfill_pass_yds_lines=true, backfill_seasons=2025
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --seasons 2025 --dry-run
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --seasons 2025 --max-credits 3000
export DATABASE_URL=...
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --assign-teams --seasons 2025
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py
```

```bash
export ODDS_API_KEY=...
cd backend
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --seasons 2023,2024 --dry-run
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --seasons 2023,2024 --max-credits 5600
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --rebuild-from-cache --seasons 2023,2024
export DATABASE_URL=...
PYTHONPATH=. python scripts/nfl_backfill_pass_yds_odds.py --assign-teams --seasons 2023,2024
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py
```

Prod replay (`nfl_backtest.py --season 2025`): QB MAE **68.4** (n=407),
kicker MAE **0.98** (n=479), QB O/U hit **46.4%** (n=386).

```bash
export DATABASE_URL=...   # Railway Postgres
cd backend
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py
PYTHONPATH=. python scripts/nfl_backtest.py --season 2025 --start-week 3 --end-week 18 --json
# S3 (needs AWS keys) — only force-upload shadow artifacts; promote still gated:
PYTHONPATH=. python scripts/nfl_prod_qb_eval.py --force-upload --upload-kickers
```

Kicker ensemble lives at `s3://yetibets/nfl/` (`NFL_MODELS_S3_PREFIX=s3://yetibets/nfl/`).
QB yards/O/U artifacts go under `s3://yetibets/nfl/ml_models/`.

**S3 upload (2026-08-11, post-#89):** v5 residual QB + O/U shadow artifacts
force-uploaded to `s3://yetibets/nfl/ml_models/`
(`gbm-qb-residual-20260811`, market-aware baseline, 28 features including
volume + `line_minus_tier`). Promote still **off** — do **not** set
`NFL_QB_ML_ENABLED=1` (holdout lift +0.9% ≪ 10%). Railway Production Deploy
for `#89` ships the same bundled pickles under `backend/models/nfl/`.

**Prior S3 upload (2026-08-11):** refreshed kicker pickles + attempts model
pushed to `s3://yetibets/nfl/`; earlier residual QB + O/U shadows under
`s3://yetibets/nfl/ml_models/`.

**Do not enable `NFL_QB_ML_ENABLED=1` until a new eval reports
`promote_recommended: true` (tier lift ≥10% **and** ML MAE < `line_mae`).**

Artifacts under `backend/models/nfl/` for shadow inference:
`qb_passing_yards.pkl` (residual), `qb_pass_yds_ou.pkl`,
`qb_prod_retrain_report.json`, `qb_prod_backtest_report.json`.
## Kicker blend (Phase 4.4+)

Each kicker has one `pred_kicker_predictions` row per game, dated with the real
Eastern kickoff and refreshed until then. The projected game is the team's next
game that has not kicked off (`kickers.upcoming_events`); roof and surface come
from `venues.py`. Earlier rows were dated "run time + 1 day", one per run, and
from Sunday night to Wednesday the projected game was the one just played.
`collect_kicker_actuals._find_prediction` grades a game against the row dated
for it, or for legacy rows the latest one written before it.

| Variable | Purpose |
|----------|---------|
| `NFL_KICKER_ML_BLEND_WEIGHT` | Override default ML blend |
| `NFL_KICKER_BLEND_TUNED_WEIGHT` | Pin walk-forward optimal weight in prod |
| `NFL_MODELS_S3_PREFIX` | Kicker ensemble pickles |

ML FG count uses **attempts × distance-mixture make%** (`kicker_volume.py`).
Attempts prefer GBM `kicker_attempts.pkl` (from `field_goal_data.csv`), else
heuristic. Live weather (`temperature`, `wind_speed`) comes from
`pred_nfl_weather`; kickers never import `weather_integration`.

Refresh make/miss ensemble + attempts:

```bash
cd backend
PYTHONPATH=. python scripts/nfl_retrain_kicker_models.py
PYTHONPATH=. python scripts/nfl_tune_kicker_blend.py --write
```

```bash
# Railway / prod recommendation until prod walk-forward exists:
NFL_KICKER_BLEND_TUNED_WEIGHT=0.5
```

## Accuracy

`GET` NFL accuracy includes `by_model_version` MAE for QB yards and kicker FG.
