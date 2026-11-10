# NFL Receiving Yards Projections — Design Spec

**Date:** 2026-11-10  
**Status:** Approved for implementation  
**Task:** YT-10 — Add NFL receiving yards projections for RB/WR/TE  
**Approach:** Clone the QB pass-yards vertical end-to-end (Approach 1)

## Problem

YetAI’s `/predictions/nfl` board already ships QB pass yards (Model / Market / Edge / Pick via soft-anchor #162), kickers, game spreads/totals, and Anytime TD. There is **no** receiving-yards model board for RB/WR/TE.

Odds API exposes `player_reception_yds`. Live Odds UI can label that market, but it is display-only. Fantasy analytics already store receiving yards / target share for fantasy points — not a betting board. Regular-season readiness explicitly deferred rush/recv props; this spec unblocks receiving yards only.

## Goals

1. Ship a **betting board** for receiving yards with the same product shape as QB: **Model / Market / Edge / Pick** (plus Conf / News as elsewhere).
2. Attach against Odds **`player_reception_yds`** only for **lined players** (universe = players with a real reception-yards line).
3. v1 model: **strong non-ML** expected yards (targets × YPR + depth / pace / matchup) + **soft-anchor** vs the line — **no residual ML** in v1.
4. One table on `/predictions/nfl` with a **position filter** (RB / WR / TE).
5. Fail closed on odds attach; never invent targets or publish raw market as “projection.”

## Non-goals (v1)

- Residual / GBM receiving-yards ML (defer until a line-vs-ML promote gate like QB `NFL_ML_OPS.md`)
- Rushing yards board (`player_rush_yds`)
- Receptions-count board (`player_receptions`) / longest reception
- Separate page or hub card; fantasy-points rewrite
- Monte Carlo game simulation as the yards engine
- Auto-pick source (follow-up after grading exists)
- Preseason product surface
- Shipping raw market line as `predicted_receiving_yards` (lesson from pre-#162 QB board)

## Locked decisions

| Decision | Choice |
|----------|--------|
| Product shape | Betting board like QB: Model / Market / Edge / Pick vs Odds `player_reception_yds` |
| Universe | **Lined players only** (must have attachable reception-yards O/U) |
| Model v1 | Strong non-ML: `targets × YPR` + depth / pace / matchup, then soft-anchor; **no residual ML** |
| UI | One PropGroup table on `/predictions/nfl` with position filter |
| Implementation approach | Clone QB vertical end-to-end (tables, ETL chain, betting attach, API group, columns) |
| Soft-anchor α | `NFL_RECV_ANCHOR_ALPHA` default **~0.25** (mostly market, small model signal) |
| Odds attach failure | **Fail-closed** — no invented lines, no fake edges |
| Missing features | Skip or low-conf; **never invent targets** |

---

## Approach

**Primary template:** QB pass-yards vertical (`qb_dynamic` → features → publish yards → `qb_betting` → weekly chain → `pred_qb_predictions` → `GET /predictions/nfl` → QB PropGroup).

**Feature / universe adjacency:** ATD skill-position stack (RB/WR/TE depth, snaps, `target_share`, schedule/game env) — reuse for who can be on a slate and for usage priors; **do not** reuse ATD λ→P(TD) math as the yards engine.

**Honesty layer:** soft-anchor yards publish (same formula as QB #162), not ATD market-anchor probability shrink (unless a later phase explicitly adds it).

```text
Odds slate (player_reception_yds lines)
  → feature build (targets, YPR, depth, pace, matchup)
  → model_yards (non-ML)
  → soft-anchor: α·model + (1−α)·line
  → edge / pick
  → pred_recv_yds_predictions
  → GET /predictions/nfl → receiving_yards_predictions
  → /predictions/nfl table + position filter
```

---

## Product surface

| Piece | Spec |
|-------|------|
| Page | `/predictions/nfl` (existing SportPredictionsPage shell) |
| Group | **Receiving Yards** PropGroup (alongside QB / Kicker / ATD) |
| Columns | Mirror QB: Model (`predicted_receiving_yards`), Market (`ou_line`), Edge, Pick, Conf, News; include **Pos** |
| Filter | Client position filter: All / RB / WR / TE |
| Hub copy | Update stats hub card desc from “QB + kicker only” to include receiving yards |
| Live Odds | Unchanged display-only path; model board is the projections surface |

---

## Model v1 (non-ML)

### Expected yards

For each lined player:

```text
expected_targets  ← usage prior (target_share × team pass attempts / pace)
                     adjusted by depth chart / injury / recent snaps
ypr               ← recent / season yards-per-reception (position-aware)
depth_adj         ← aDOT / depth-of-target lean vs opponent pass defense
pace_adj          ← team implied pass volume from game totals / script
matchup_adj       ← opponent receiving yards / YPR allowed (by pos when available)

model_yards = expected_targets × ypr × depth/pace/matchup factors
```

Exact factor parameterization is an implementation detail; invariants:

1. **Targets are never invented** — if target/share/snap priors are missing, skip the player or mark **low-conf** and do not fabricate a target rate from the line.
2. Model yards are independent of the O/U until soft-anchor.
3. No GBM / residual ML path in v1 (no `ml_shadow_yards`, no `NFL_RECV_ML_ENABLED`).

### Soft-anchor publish

Reuse the QB helper pattern (`soft_anchor_qb_yards` or a shared yards soft-anchor):

```text
published = α · model_yards + (1 − α) · ou_line
α = NFL_RECV_ANCHOR_ALPHA   # default 0.25
prediction_method = soft_anchor
edge = published − ou_line
```

- Never set `predicted_receiving_yards = ou_line` as the sole publish when a model exists (avoid pre-#162 “market as projection”).
- If model yards cannot be computed but a line exists: **skip or low-conf PASS** — do not publish market-as-model.
- Edge % and OVER / UNDER / PASS thresholds should mirror QB yards recommender conventions (edge % of line; disagreement → PASS where a classifier exists later).

---

## Player universe

**Lined players only.**

1. Build the week’s Odds `player_reception_yds` slate (per-event markets).
2. Resolve players to RB / WR / TE (drop QB / unknown unless a line truly exists and position maps cleanly — default product is skill-position receiving).
3. Feature-join only those player_ids.
4. No depth-chart “WR1–3” expansion for unlined players in v1.

Rationale: board is a betting product; unlined rows cannot show Market / Edge / Pick honestly. Fail-closed attach reinforces this.

---

## Data model

| Table | Role |
|-------|------|
| `pred_recv_yds_predictions` | Weekly board rows: player, position, team, opponent, season, week, game_date, `predicted_receiving_yards`, `ou_line`, edge fields, recommendation, confidence, `prediction_method`, feature JSON / model_version |
| `pred_recv_yds_actuals` | Post-week actual receiving yards for grading / accuracy |

Unique key: `(season, week, player_id)` (and/or `game_date` + player), matching QB / ATD patterns.

Suggested core columns (align names with API / UI):

| Field | Notes |
|-------|-------|
| `predicted_receiving_yards` | Soft-anchored (or skipped) publish |
| `model_yards` / feature blob | Pre-anchor model for debugging / accuracy |
| `ou_line` | Market reception yards line |
| `edge`, `edge_percentage` | Publish − line |
| `betting_recommendation` | OVER / UNDER / PASS |
| `confidence` | Low when features thin |
| `position` | RB / WR / TE |
| `prediction_method` | `soft_anchor` (v1); never `market_line` as honesty path |

---

## Pipeline / ETL

Clone QB leaf structure under `backend/app/services/etl/nfl/`:

| Module (suggested) | Role |
|--------------------|------|
| `recv_yds_features.py` | Build targets / YPR / depth / pace / matchup features (reuse ATD weekly/snap/target_share + game lines) |
| `recv_yds_projector.py` | Features → `model_yards` → soft-anchor when line present → upsert `pred_recv_yds_predictions` |
| `recv_yds_betting.py` | Odds `player_reception_yds` attach → line, edge, pick; fail-closed |
| `recv_yds_weekly.py` | Chain: slate/features → project → betting |
| `collect_recv_yds_actuals.py` | Grade actuals → `pred_recv_yds_actuals` |

### Order of operations

1. **Odds slate** — fetch `player_reception_yds` for the week’s events (share Odds budget with QB / ATD / game lines).
2. **Features** — join nflverse / ATD-adjacent usage + `pred_nfl_game_lines` pace/env; skip or low-conf when targets cannot be estimated honestly.
3. **Model yards** — non-ML formula.
4. **Soft-anchor** — blend with attached line (`NFL_RECV_ANCHOR_ALPHA`).
5. **Edge / pick** — write recommendation fields.
6. **Persist** — `pred_recv_yds_predictions`.

### Fail-closed semantics

| Condition | Behavior |
|-----------|----------|
| Odds attach miss / budget exhaustion / no line | Do **not** invent `ou_line`; no synthetic Market/Edge; row omitted or left unmatched without pick |
| Missing targets / critical features | Skip player or publish only with **low confidence** and no fabricated target rate |
| Name/id resolve failure | Skip; never force-match |

Add `player_reception_yds` to Odds discovery / `FALLBACK_PLAYER_PROP_MARKETS` if discovery fails (catalog already lists it in `PLAYER_PROP_MARKETS`).

### Celery / Beat

- New leaf in `NFL_PHASES` predictions (and gameday where QB runs), e.g. `nfl.recv_yds_weekly`.
- Weekly cadence aligned with QB/ATD props; optional midweek refresh with ATD.
- **Share** the existing Odds credit budget; document incremental per-event cost for `markets=player_reception_yds`.
- Update `NFL_ETL_PARITY.md` / ops notes when implementing (implementation PR — not this spec commit).

### Accuracy / auto-pick (follow-on in same vertical)

- Extend `nfl_accuracy_service` with receiving-yards MAE buckets once actuals exist.
- Auto-pick source (clone `nfl_qb_passing_source.py`) is a **follow-up**, not a v1 ship gate.

---

## API

Extend `GET /api/v1/predictions/nfl` with:

```json
"receiving_yards_predictions": [ /* lined RB/WR/TE rows for selected date/week */ ]
```

Required response fields for UI:

- Identity: `player_id`, `player_name`, `position`, `team`, `opponent`, `game_date` / week / season  
- Board: `predicted_receiving_yards`, `ou_line`, edge (+ %), `betting_recommendation` / pick, `confidence`  
- Method: `prediction_method` (`soft_anchor`)

Sort default: absolute edge or model yards (implementation may match QB ordering). Date picker behavior must stay consistent with other prop groups (pass game date like UI does today).

OpenAPI: regenerate `docs/api/openapi*.json` when routes/schemas change (implementation PR).

---

## Frontend

| Change | Detail |
|--------|--------|
| PropGroup | `responseKey: 'receiving_yards_predictions'` on `predictions/nfl/page.tsx` |
| Columns | New `NFL_RECV_YDS_COLUMNS` in `propProjectionDisplay.ts` (QB-shaped + Pos) |
| Filter | Position filter control on the receiving-yards table (All / RB / WR / TE) |
| Hub | Stats hub card copy includes receiving yards |
| Flags | No separate UI kill-switch required for v1 unless ops wants one; prefer ship with board when ETL+API green |

---

## Configuration

| Env | Default | Meaning |
|-----|---------|---------|
| `NFL_RECV_ANCHOR_ALPHA` | `0.25` | Model weight α in `α·model + (1−α)·line` |
| Odds budget (existing) | shared | Must cover added `player_reception_yds` pulls |

No `NFL_RECV_ML_ENABLED` in v1.

---

## Testing & acceptance

### Unit / contract (implementation)

1. **Soft-anchor** — given model=100, line=80, α=0.25 → publish = `0.25·100 + 0.75·80 = 85.0`; α clamp [0,1]; NaN env → default.
2. **Fail-closed odds** — attach miss ⇒ no invented `ou_line` / no OVER-from-null; unmatched count stays honest.
3. **Never invent targets** — missing target features ⇒ skip or low-conf path; assertion that synthetic targets are not derived from the line alone.
4. **API fields** — `receiving_yards_predictions` includes Model / Market / Edge / Pick fields; lined-only universe.
5. **UI filter** — position filter shows only RB / WR / TE as selected (component or display-lib test).

### Acceptance (product)

- `/predictions/nfl` shows a Receiving Yards table with Model ≠ Market (unless α→0) when lines + features exist.
- Non-zero edges appear; picks are not mass PASS from publishing the line as the model.
- Unlined players do not appear.
- Odds budget exhaustion does not fabricate a board.
- Position filter works for RB / WR / TE.

---

## Success criteria

1. ETL weekly chain produces soft-anchored rows in `pred_recv_yds_predictions` for lined RB/WR/TE.
2. `GET /predictions/nfl` returns `receiving_yards_predictions` with QB-shaped board fields.
3. UI table live on `/predictions/nfl` with position filter.
4. Soft-anchor + fail-closed + no-invented-targets tests green.
5. No residual ML path or market-as-projection publish in v1.

## Follow-ups

- Residual ML + historical `player_reception_yds` backfill + line-vs-ML promote gate (mirror QB Phase C)
- Rushing yards board (`player_rush_yds`) as a sibling vertical
- Auto-pick source + accuracy page buckets
- Optional ATD-style market shrink on top of soft-anchor if edges over-disperse
- Midweek Beat alignment with ATD / game-board tune

## References

- Briefing: Project store `internal/nfl-receiving-yards-board-briefing.md`
- QB soft-anchor: PR #162; `qb_passing_yards_ml.soft_anchor_qb_yards`; `NFL_ML_OPS.md`
- ATD market-anchor: PR #130; `NFL_ANYTIME_TD.md` (universe/features adjacency only)
- Deferred props note: `docs/superpowers/specs/2026-08-10-nfl-regular-season-readiness-design.md`
- Design sibling: `docs/superpowers/specs/2026-08-10-nfl-anytime-td-design.md`
