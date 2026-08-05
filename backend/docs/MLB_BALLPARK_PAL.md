# MLB Ballpark Pal (BPP) ops

Ballpark Pal supplies **model priors** for YetAI MLB predictions — not sportsbook odds. Market lines remain on The Odds API; BPP `odds` fields are model-implied only.

Design reference: [Ballpark Pal MLB features spec](../../docs/superpowers/specs/2026-08-05-ballpark-pal-mlb-features-design.md).

## Enablement

### Railway (production)

Set vars on **both** Railway services — **YetAI** (API) and **celery-worker**:

1. `BALLPARK_PAL_API_KEY` — add on both services; redeploy/restart.
2. Leave `BALLPARK_PAL_ENABLED` unset (default `0`) until the first successful sync appears in celery-worker logs (`ballpark_pal.status=ok` with game/player counts).
3. Then set `BALLPARK_PAL_ENABLED=1` on **celery-worker** (and YetAI if you run projections locally against prod).
4. Prior weights use defaults below unless you tune them via env (no redeploy needed for weight changes).

Do **not** flip `BALLPARK_PAL_ENABLED=1` in prod until step 2 confirms snapshots are landing.

### Local / general

1. Set `BALLPARK_PAL_API_KEY`.
2. Set `BALLPARK_PAL_ENABLED=1` when ready to sync.
3. Confirm pipeline log: `ballpark_pal.status=ok` with game/player counts, or `skipped` when disabled.

Prior weights are tunable without redeploying code (env only).

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `BALLPARK_PAL_ENABLED` | `0` | Master switch (`1`/`true`/`yes`/`on`) |
| `BALLPARK_PAL_API_KEY` | — | API key (`X-API-Key` header); never commit |
| `BALLPARK_PAL_BASE_URL` | `https://www.ballparkpal.com/api/v1` | Optional host override |
| `BPP_GAME_PRIOR_WEIGHT` | `0.30` | Blend BPP team `runs` into MC λ (clamped 0–1) |
| `BPP_K_PRIOR_WEIGHT` | `0.25` | Strikeout mean prior toward BPP pitcher K |
| `BPP_HITS_PRIOR_WEIGHT` | `0.25` | Hits board relative multiplier weight |
| `BPP_HR_PRIOR_WEIGHT` | `0.25` | HR board relative multiplier weight |

Module layout: `app/services/ballpark_pal/` (`client`, `config`, `sync`, `store`, `priors`, `inject_game`).

## Daily API budget

Per slate (approximate):

| Call | Count |
|------|-------|
| `GET /games?date=` | 1 |
| `GET /parkfactors?date=` | 1 |
| `GET /parkfactors/hitters?date=` | 1 |
| `GET /matchups?date=&starters=true` | 1 |
| Per game: `projections/averages` + `projections/probabilities` | 2 × N |

**~4 + 2N requests/day** (~**35 req/day** for a 15-game slate). Vendor default quota is ~15,000 req/month (~60 req/min). Client honors one `Retry-After` on 429 then soft-fails.

**Not used in v1:** `matchups/predict` (any-pair fan-out). Starter matchups come from the date-level `matchups` endpoint only.

## Pipeline hook

Early in `pipeline.run_projections_phase`:

1. `sync_ballpark_pal_slate(today)` — fetch + upsert snapshot tables.
2. Downstream predictors read today's rows via `store` loaders.

Soft-fail everywhere: auth/quota/5xx/partial mapping never aborts the MLB slate.

## What gets injected (v1)

### Game / Monte Carlo

- After lineup adjustments, blend BPP full-game team `runs` into MC lambdas (`inject_game.maybe_apply_bpp_run_priors`).
- Apply game-level `runsPercent` park factor when present.
- Metadata under `sim_distribution.matchup_meta.bpp`.
- When MC + BPP apply, `model_version` gains an MC/BPP suffix (see below).

### Strikeouts

- Prior toward BPP pitcher projected K; optional shrink from BvP `strikeoutProbability`.
- When a K prior applies, `matchup_source` is set to **`ballpark_pal`** (evidence tag on `pred_pitcher` / `pred_strikeout_projections`).

### Hits / HR boards

- **Scale-neutral relative multipliers** — not absolute blend into heuristic scores.
- Baselines: **1.0 hits** / **0.15 HR** per game; multiplier clamp **0.5–1.5**.
- HR path may shrink BPP `homeRuns` toward matchup `homeRunProbability`, then apply hitter `homeRuns` park factor.

## Model version tag

Logical suffix is `+mc+bpp` when both Monte Carlo and BPP game priors apply. `normalize_model_version()` persists a DB-safe form, e.g. **`ensemble-v123-mc-bpp`** (plus signs become hyphens, max 20 chars).

Filter game accuracy by this tag vs pre-BPP `-mc` rows when comparing lift.

## Rollout

1. **Shadow:** enable sync only (`ENABLED=1`); verify snapshot counts in pipeline logs.
2. **Priors:** keep default weights; watch mapping misses in logs.
3. **Graded success (~2–4 weeks):** compare vs pre-BPP baseline using existing accuracy services — no new dashboards required:
   - **Game ML / totals:** Brier, O/U hit rate (`mlb_accuracy_service` game buckets).
   - **Strikeouts:** O/U graded counts + `strikeout_by_model_version`; filter rows where `matchup_source=ballpark_pal`.
   - **Hits / HR:** graded hit-rate buckets on projected vs actual boards.

Lift → keep or tune weights. Flat/worse → set prior weights to `0` (or `BALLPARK_PAL_ENABLED=0`); snapshots can keep collecting for v2 retrain.

## Rollback

| Action | Effect |
|--------|--------|
| `BALLPARK_PAL_ENABLED=0` | Skip sync + all priors; pipeline identical to pre-BPP |
| Set `BPP_*_PRIOR_WEIGHT=0` | Keep snapshots; disable blending only |
| Revert deploy | Same as disabled if env not set |

Never fail the projections phase solely because BPP failed.

## Smoke test (no DB, no network)

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_ballpark_pal.py
```

Optional live connectivity (requires key; never prints it):

```bash
PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_ballpark_pal.py --live
```

## Unit tests

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_mlb_ballpark_pal_*.py \
  tests/test_mlb_monte_carlo.py \
  tests/test_mlb_matchup_k.py -q
```

## Related

- Monte Carlo: [MLB_MONTE_CARLO.md](./MLB_MONTE_CARLO.md)
- ML ops / backtest: [MLB_ML_OPS.md](./MLB_ML_OPS.md)
- Matchup profiles (separate from BPP): [MLB_MATCHUP_PROFILES.md](./MLB_MATCHUP_PROFILES.md)
- Pipeline orchestrator: `app/services/etl/mlb/pipeline.py`
