# Ballpark Pal → MLB Prediction Features — Design

**Date:** 2026-08-05  
**Status:** Approved (brainstorming)

## Goal

Use [Ballpark Pal API](https://www.ballparkpal.com/api/docs/) as **model priors / features** so YetAI MLB predictions are more accurate on graded boards (game ML/totals, strikeouts, hits, HR) — not as a soft replace of our stack or a sportsbook odds source.

## Decision summary

| Choice | Selection |
|--------|-----------|
| Integration mode | **B** — Prior / features into our models |
| Scope | **C** — Game + player props in one pass |
| History gap | **B** — Snapshot daily + grow; runtime priors now; retrain later |
| Success bar (v1) | **A** — Graded board lift (Brier / hit rate) over ~2–4 weeks |
| Architecture | **Approach 2** — Feature injection into existing predictors |
| Sportsbook source | Unchanged — The Odds API for market lines / EV |
| BPP `odds` field | Model-implied only; never treat as book prices |

## Constraints (vendor)

- Auth: `X-API-Key` header; base `https://www.ballparkpal.com/api/v1`
- Data: **today and future only** (US Eastern); no historical projections (`date_out_of_range`)
- Quota: ~15,000 req/month default; ~60 req/minute; respect `Retry-After` on 429
- Included: model probabilities, simulated averages, park factors (stadium + weather components), BvP matchups
- Not included: sportsbook odds, raw weather forecasts, historical backfill

## Architecture

```
Daily MLB projections phase (Celery)
  │
  ├─ BallparkPalClient
  │     games(date)
  │     projections/probabilities + averages (per game)
  │     parkfactors + parkfactors/hitters (date)
  │     matchups(date, starters=true)
  │
  ├─ bpp_snapshot_store  (raw + normalized rows)
  │
  ├─ bpp_feature_mapper  (BPP gameId/playerId/teamId → StatsAPI ids)
  │
  └─ inject into existing predictors
        game_projection_pipeline / monte_carlo
        strikeouts matchup path
        hits / HR boards
        (Odds API remains market side for EV)
```

**v1:** runtime prior formulas when snapshots map; missing BPP → existing path unchanged.  
**v2:** same snapshot tables become training features once enough graded days exist.

## Components

### Config / secrets

| Env | Purpose |
|-----|---------|
| `BALLPARK_PAL_API_KEY` | API key (Railway / local `.env` only; never commit) |
| `BALLPARK_PAL_ENABLED` | Master switch (`0`/`1`) |
| `BALLPARK_PAL_BASE_URL` | Optional override (default production `www` host) |
| `BPP_GAME_PRIOR_WEIGHT` | Blend weight into MC λ / game runs (default ~0.25–0.35) |
| `BPP_K_PRIOR_WEIGHT` | Strikeout prior weight |
| `BPP_HITS_PRIOR_WEIGHT` / `BPP_HR_PRIOR_WEIGHT` | Batter board prior weights |

### Client

Package: `backend/app/services/ballpark_pal/`

- Thin sync HTTP client (ETL-friendly), `X-API-Key`, JSON `meta`/`data`/`error` envelopes
- Methods: `health`, `games`, `projections_probabilities`, `projections_averages`, `parkfactors`, `parkfactors_hitters`, `matchups`
- Soft-fail on auth/quota/5xx; log `requestId`; caller tags for ops
- **No** daily fan-out of `matchups/predict` (quota)

### Snapshot tables

Exact SQLAlchemy names may vary; logical stores:

1. **`bpp_game_snapshots`** — date, `bpp_game_id`, our `game_pk` (nullable until mapped), home/away team ids, `as_of`, payloads for probabilities + averages (JSON or normalized FK children)
2. **`bpp_player_proj_snapshots`** — per player/game averages + selected market probs (pitcher K, batter hits/HR, etc.)
3. **`bpp_park_factor_snapshots`** — game-level PF + per-hitter combined/stadium/weather multipliers
4. **`bpp_matchup_snapshots`** — batter/pitcher starter matchup probs + vsTypical for the date

Idempotent upserts on `(date, bpp_game_id)` / `(date, game, player)` keys so re-runs refresh the same slate.

### ID mapping

BPP `gameId` / `playerId` / `teamId` align with MLB StatsAPI-style ids. Map to ids already used in `pred_*` and schedule sync. Unmapped rows are logged and skipped — never invent joins.

### Pipeline hook

New step early in `pipeline.run_projections_phase` (or immediately before game/prop predict):

1. If disabled or no key → no-op  
2. Fetch date-level + per-game endpoints  
3. Upsert snapshots  
4. Downstream predictors read today’s snapshots via mapper helpers  

Estimated daily volume: ~4 date-level calls + 2×N games ≈ **~35 req/day** for a full slate.

## Feature injection (v1 priors)

### Game / Monte Carlo

- After `predict_games`, during MC λ setup: blend BPP full-game team `runs` into `home_lambda` / `away_lambda` with `BPP_GAME_PRIOR_WEIGHT`
- F5 (`runsFirstFive`) is **not** used in v1 game priors ( defer to a later tweak if graded totals need it)
- Apply game-level / hitter-aggregated park factor vs neutral when available
- Record both raw and BPP-adjusted summaries; suffix `model_version` with `+bpp` when applied

### Strikeouts

- In matchup adjustment path (same seam as profiles): prior toward BPP pitcher projected K and/or Pitcher Strikeouts market average
- Optional shrink using BvP `strikeoutProbability` when starter matchup exists
- Tag enrichment / `matchup_source` with `ballpark_pal` when used

### Hits / HR

- Prior projected hits/HR toward BPP batter averages
- Scale HR expectation by hitter-specific `homeRuns` park factor when present
- Second shrink from matchup `homeRunProbability` / hit probabilities vs typical

### EV / value bets

- Unchanged: Odds API = market implied; YetAI (BPP-informed) probs = model side
- Do not substitute BPP American `odds` for book prices

## Error handling

| Condition | Behavior |
|-----------|----------|
| Key missing / `ENABLED=0` | Skip; pipeline identical to today |
| 401/403 / quota / 5xx | Log; skip enrichment; complete slate |
| 429 | Honor `Retry-After` once; then skip remaining BPP for that run if still limited |
| Partial mapping | Enrich mapped games/players only |
| Bad payload | Skip that resource; continue |

Never fail the MLB projections phase solely because BPP failed.

## Testing

- Unit: client envelope parsing, ID mapper, prior blend/shrink math with recorded fixture JSON
- Pipeline: disabled path unchanged; enabled + mocked client asserts snapshots + `+bpp` / source tags
- CI: no live API key required

## Rollout & success

1. Client + migrations + daily snapshot (shadow OK before priors)
2. Enable priors via flags/weights
3. Compare graded boards ~2–4 weeks vs pre-BPP baseline using existing accuracy services:
   - Game ML / totals (Brier, hit rate)
   - Strikeout / hits / HR boards
4. Lift → keep / tune weights; plan v2 retrain on snapshots  
   Flat or worse → set weights to 0; keep collecting snapshots

## Out of scope (v1)

- UI / DFS fantasy point surfaces
- Historical BPP backtest or vendor historical API
- Replacing Odds API or our core models wholesale
- Daily `matchups/predict` any-pair fan-out
- Retrain of XGBoost / strikeout classifier / HR models on BPP features (v2)

## Key integration touchpoints (existing code)

| Area | Path |
|------|------|
| Orchestrator | `backend/app/services/etl/mlb/pipeline.py` |
| Game + MC | `game_projection_pipeline.py`, `monte_carlo.py` |
| Strikeouts | `strikeouts.py`, lineup matchup adjustment |
| Hits / HR | `hits.py`, HR prediction path |
| EV | `mlb_ev.py` (market side unchanged) |
| Accuracy | `mlb_accuracy_service.py` |
| Config pattern | `app/core/config.py` + Odds API-style env handling |

## Open follow-ups (implementation plan, not blockers)

- Exact Alembic table/column shapes
- Default prior weights via smoke on a live slate
- Admin/ml-ops visibility for last BPP pull / mapping miss rate
