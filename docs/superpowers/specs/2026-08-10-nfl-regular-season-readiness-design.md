# NFL Regular-Season Readiness + Game Projections v1

**Date:** 2026-08-10  
**Status:** Approved for implementation planning  
**Context:** Preseason has begun; goal is accurate 2026 REG predictions and a real game board on `/predictions/nfl` before Week 1.

## Problem

YetAI’s NFL surface is prop-only (QB pass yards + kicker FG). The predictions page advertises game slate projections, but the frontend hardcodes empty rows. Calendar/season defaults still point at **2025**, so without `NFL_SEASON=2026` the pipeline can treat August 2026 as late 2025. QB rows use pipeline-run `game_date` instead of kickoff, so the date picker often shows an empty slate on game day.

## Goals

1. **Prop readiness (Track A):** Correct season/week, kickoff dates, kicker season defaults, and prop pipeline hygiene for 2026 REG.
2. **Game projections v1 (Track B):** NBA/WNBA-shaped spread + totals + win probability, with Elo seeded from nflverse REG games **2023–2025**.
3. Wire API + `/predictions/nfl` so game cards render from real model output.

## Non-goals (v1)

- Drive/possession Monte Carlo (MLB-parity)
- Preseason as a product surface
- Rushing / receiving props
- Player-availability XGBoost spread model (NBA ML path)
- Full Beat schedule retune beyond adding game-projection phases

## Approach

**Clone the NBA/WNBA Phase-1 pattern**, not MLB Monte Carlo:

- Odds API → game lines table
- Elo (+ scoring overlay) → spread / win-prob projections
- Team PPG matchup → totals projections
- Frontend `mergeSpreadTotalsGameProjections` for NFL

Elo cold-start: **seed from prior seasons** (nflverse 2023–2025 REG), then update weekly from finals.

---

## Track A — Prop readiness

| Issue | Fix |
|-------|-----|
| `DEFAULT_NFL_SEASON = 2025` | Bump to **2026**; document `NFL_SEASON` in `.env.example` |
| Week math | Keep REG week 1–18; before first Thursday → week 1. Filter nflverse schedules to **REG** only when resolving opponents |
| QB `game_date = datetime.now()` | Persist **kickoff** from schedule so API date filter matches game day |
| Kicker ESPN `season_year=2024` default | Use `get_nfl_season()`; `seasontype=2` (REG) only |
| Stale QB tier names | Refresh 2026 starters/rookies in tier table; ops may enable `NFL_QB_ML_ENABLED=1` when S3 GBM present |
| Odds “in season” | Keep Sep–Feb for REG props; no August preseason prop requirement in v1 |
| Dead `qb_dynamic_heroku` fallback | Remove or replace with in-repo `qb_dynamic` path |

Docs drift: update `NFL_ETL_PARITY.md` (Beat is already scheduled; API does not return rushing).

---

## Track B — Game projections architecture

```text
nflverse REG schedules (2023–2025)
        ↓ seed Elo (one-off / re-runnable)
Odds API (h2h, spreads, totals) → pred_nfl_game_lines
        ↓
spread_projector (Elo + scoring overlay) → pred_nfl_spread_projections
totals_projector (team PPG matchup)      → pred_nfl_totals_projections
        ↓ (weekly after finals)
spread/totals actuals → Elo update + accuracy buckets
        ↓
GET /api/v1/predictions/nfl → qb + kickers + spreads + totals
        ↓
FE mergeSpreadTotalsGameProjections (nfl case)
```

### Data model

New tables (NBA-shaped, NFL-prefixed):

| Table | Purpose |
|-------|---------|
| `pred_nfl_game_lines` | Kickoff, spread, total, ML, book, Odds API event id |
| `pred_nfl_spread_projections` | Projected margin, home/away WP, market spread, edge, recommendation, confidence |
| `pred_nfl_totals_projections` | Projected home/away points + total, market total, edge, O/U recommendation |
| `pred_nfl_spread_actuals` | Final scores for Elo + ATS grading |
| `pred_nfl_totals_actuals` | Final total for O/U grading |

Optional but preferred: `pred_nfl_team_elo` snapshot (`team_name`, `elo`, `as_of_date`) so daily runs do not rescan full history. **Source of truth** remains chronological actuals; snapshot is a cache rebuilt from seed + weekly updates.

Unique constraint: `(game_date, home_team_name, away_team_name)`.

Team name normalizer: single map Odds API ↔ nflverse ↔ display (include Washington / franchise alias handling).

### Elo seeding

1. Job `nfl.seed_elo_history`: load nflverse REG games for seasons **2023, 2024, 2025** in chronological order; run through shared `load_elos_from_actuals`.
2. Persist ending ratings to snapshot (and/or write historical rows into `pred_nfl_spread_actuals` for rebuildability).
3. Each week after REG finals: write actuals → `update_elo` → refresh snapshot.
4. Relocations/rebrands handled only in the name normalizer.

### NFL `SpreadLeagueConfig`

Reuse `backend/app/services/etl/_spread_model.py` with an `NFL_CONFIG`:

| Param | v1 value | Notes |
|-------|----------|--------|
| `home_court_advantage` | 2.5 | Points of HFA |
| `edge_threshold` | 3.0 | Matches FE NFL card threshold |
| `initial_elo` | 1500 | Pre-seed only for brand-new teams |
| `elo_k` / `spread_per_elo` / logistic scale | Start from NBA defaults | Tune later via ATS backtest; not a Week-1 blocker |

### Totals v1

- Team offensive / defensive PPG from nflverse (prior season + current REG when available).
- Projected scores from matchup blend; **align** home/away points to projected margin so scores are consistent with spread (same approach FE already uses for NFL display).
- Weather overlay: optional light adjustment using existing `pred_nfl_weather` / CSV if low-cost; not required to ship v1.

### Pipeline (`NFL_PHASES`)

1. **actuals** — existing QB/kicker actuals; add spread/totals actuals when scores final  
2. **game lines** — `nfl.update_game_lines` (Odds API `americanfootball_nfl`)  
3. **game projections** — `nfl.spread_projector`, `nfl.totals_projector`  
4. **props** — existing `nfl_qb_weekly`, `nfl_kickers`

Elo seed is a **one-off / admin** task before Week 1, not every Beat tick.

Beat: keep daily ~4:30; midweek lines refresh is a follow-up, not blocking.

### API

`GET /api/v1/predictions/nfl` response shape:

```json
{
  "qb_predictions": [],
  "kicker_predictions": [],
  "spreads": [],
  "totals": []
}
```

Attach `game_time` from `pred_nfl_game_lines` (NBA pattern). Fix docstring (passing yards + kickers + game lines; no rushing claim).

`GET /api/v1/predictions/nfl/accuracy`: add ATS and totals O/U buckets when actuals exist; keep existing QB/kicker buckets.

### Frontend

In `gameProjectionsFromApi.ts`:

```ts
case 'nfl':
  rows = mergeSpreadTotalsGameProjections(
    (data.spreads as Row[]) ?? [],
    (data.totals as Row[]) ?? [],
  );
  break;
```

`GameProjectionsSection` variant `nfl` already configures sport key, pts unit, and spread edge 3.0. Subtitle on the NFL page already mentions game slate — leave as-is once data flows.

Empty state: only when game merge rows and prop tables are all empty.

### Verification

- Unit: Elo seed determinism; spread/totals recommendation thresholds; `nfl_common` 2026 week math; REG schedule filter
- API: response includes `spreads` / `totals`; OpenAPI export if routes/shape change meaningfully
- FE: merge path returns rows when API populated
- Regression: existing `nfl_backtest --quick` stays green
- Ops: prod either sets `NFL_SEASON=2026` or relies on new code default; confirm Odds API key and Beat worker healthy before Week 1

---

## Success criteria

1. With no env override, `get_nfl_season()` returns **2026** after deploy.
2. QB/kicker predictions for a Sunday slate appear when the user selects that Sunday (kickoff-based `game_date`).
3. `/predictions/nfl` shows non-empty game projection cards for weeks with Odds API lines and projector output.
4. Elo ratings for Week 1 reflect 2023–2025 REG history (not flat 1500 for all teams).
5. Prop backtest CI baseline still passes.

## Follow-ups (explicitly later)

- Midweek Beat refresh for line movement
- ATS/totals calibration and `elo_k` tuning
- Optional weather overlay on totals
- QB GBM promote decision after 2025/26 training refresh
- Monte Carlo / possession model research
