# Automated YetAI Bet Selection — Design

**Date:** 2026-05-22
**Status:** Draft for review
**Owner:** Ben

## Goal

Automate the daily selection of 1–4 "YetAI Bets" across all leagues and market types (moneyline, spread, totals, player props) based on our projections and a unified confidence score. Picks land in a pending queue, where an admin approves, edits, or rejects them through the existing admin portal. Approved picks are tier-gated (FREE / PRO / ELITE) by confidence rank.

## Non-Goals (v1)

- Auto-publishing picks without admin approval.
- Cross-market correlated parlays.
- User-personalized YetAI picks.
- New end-user notification infrastructure (assume existing notifier handles tier-gated delivery once a bet goes live).

## Decisions

| Topic | Decision |
|---|---|
| Confidence | Build a new unified score; primary signal is edge (our projection vs market line). |
| Market coverage | Selector handles partial coverage — providers without projections return no candidates. |
| Confidence factors | Edge, historical accuracy, sample size / freshness, line movement, odds sanity, correlation guard. |
| Cadence | Scheduled daily run; picks land in `PENDING_APPROVAL` queue; admin approves in portal. |
| Tier gating | By confidence rank: rank 1 → FREE, ranks 2–3 → PRO, rank 4 → ELITE. |
| Selection volume | 1–4 picks per day; fewer (even zero) if not enough candidates clear the score threshold. |

## Architecture

Five new modules, each with one clear responsibility:

### 1. `CandidateProvider` (interface)

Protocol with a single method:

```
get_candidates(date_range) -> list[BetCandidate]
```

`BetCandidate` carries: `market_type` (ML / spread / total / prop), `league`, `event_id`, `selection` (side, over/under, player+stat), `market_line`, `market_odds`, `our_projection`, `projection_metadata` (sample size, model id, generated_at).

Concrete implementations (thin adapters over existing prediction services):
- `MLCandidateProvider`
- `SpreadCandidateProvider`
- `TotalsCandidateProvider`
- `PlayerPropCandidateProvider`

A provider that has no projections for the requested range returns `[]`. This is how the system handles uneven coverage across leagues/markets without special-casing.

### 2. `ConfidenceScorer`

Pure function:

```
score(candidate: BetCandidate, context: ScoringContext) -> ConfidenceScore
```

`ScoringContext` is loaded once per run and contains everything the scorer needs (historical accuracy stats, line movement snapshots, scoring weights from config). No I/O inside the scorer — fully testable with fixtures.

Output:

```
ConfidenceScore(
  total: float,           # 0–100
  breakdown: dict,        # {edge: 38.2, historical: 14.0, freshness: 12.0, ...}
  reasoning: str,         # human-readable explanation shown to admin
)
```

#### Sub-scores and starting weights

| Sub-score | Weight | Description |
|---|---|---|
| Edge | 40% | Distance between our projection and market line, normalized per market type so different scales (e.g., strikeouts vs spread points) are comparable. |
| Historical accuracy | 20% | Rolling 90-day hit rate for this `(market_type, league)` combo, sourced from `performance_tracker`. |
| Sample size / freshness | 15% | Penalty for small sample (e.g., pitcher with <5 starts), stale data (>24h), recent injury/lineup changes. |
| Line movement | 10% | Bonus when market moved toward our side since open; penalty if it moved against. |
| Odds sanity | 10% | Bell-curve around -150 to +150; softer falloff to -300/+400. Hard cutoffs handled in selector. |
| Projection model confidence | 5% | If the underlying ML model exposes variance/confidence, use it; otherwise neutral. |

Weights and the score threshold live in a `scoring_config` DB row, so they can be tuned without redeploy.

### 3. `BetSelector`

Inputs: list of scored candidates. Logic:

1. Drop any below the score threshold (default **65**).
2. Sort by total score, descending.
3. Apply correlation guard: skip any candidate whose `event_id` is already represented in the picks, plus known correlated cross-market cases (e.g., ML + spread same team).
4. Apply hard odds cutoff: skip anything outside `[-300, +400]`.
5. Take top N (1–4).
6. Assign tier by rank: 1 → FREE, 2–3 → PRO, 4 → ELITE.

If fewer than 4 candidates clear the threshold, publish fewer. Zero picks is a valid outcome — better than forcing weak bets.

### 4. `AutoPickOrchestrator`

The Celery task entry point. Coordinates the run:

1. Load `ScoringContext` (historical accuracy, line movement, scoring config, today's slate).
2. Fan-out to all providers in parallel (`asyncio.gather`).
3. Score every candidate.
4. Run the selector.
5. Persist picks as `YetAIBet` rows with `status=PENDING_APPROVAL`, attaching `confidence_score`, `score_breakdown`, `reasoning`, and `auto_pick_run_id`.
6. Write an `AutoPickRun` audit row with candidates considered, candidates dropped (and reasons), candidates selected.
7. Send "picks pending approval" admin notification via the existing `notification_router`.

Only this module touches the DB and Celery. Providers, scorer, and selector remain I/O-free at their boundaries.

### 5. Admin portal additions

- New **Pending YetAI Picks** view: today's picks with score, breakdown, reasoning, and a collapsed list of dropped candidates (with drop reasons).
- Per-pick actions: **Approve** (status → live, visible to assigned tier and above), **Edit** (adjust selection / line / tier / reasoning), **Reject** (status → REJECTED, kept for audit).
- **Approve all** for fast days.
- Manual bet creation continues to work unchanged.

## Data Model Changes

**Extend `yetai_bets`:**
- `confidence_score: Float | null`
- `score_breakdown: JSONB | null`
- `reasoning: Text | null`
- `source: Enum('manual', 'auto')`
- `status`: extend existing enum with `PENDING_APPROVAL`, `REJECTED`, `EXPIRED`
- `auto_pick_run_id: FK(auto_pick_runs.id) | null`

**New `auto_pick_runs`:**
- `id`, `run_at`, `status` (`success` / `partial` / `failed` / `no_picks`), `candidates_considered: int`, `candidates_selected: int`, `dropped_reasons: JSONB`, `error: Text | null`

**New `scoring_config`** (single-row, admin-editable):
- Sub-score weights, score threshold, odds bounds, correlation rules. Loaded at the start of each run.

## Data Flow

1. **9:00 AM ET** (configurable) — Celery beat triggers `auto_pick_yetai_bets`.
2. Orchestrator loads `ScoringContext` once.
3. Providers run in parallel, returning candidates (or `[]`).
4. Scorer assigns 0–100 score + breakdown + reasoning to each candidate.
5. Selector filters, ranks, applies correlation/odds guards, picks top 1–4, assigns tier.
6. Picks persist as `PENDING_APPROVAL`. `AutoPickRun` audit row written. Admin notified.
7. Admin reviews in portal → approve / edit / reject.
8. Approved picks become visible to subscribers per tier. Existing bet-verification pipeline grades them when games finalize.

## Failure Modes

| Scenario | Behavior |
|---|---|
| One provider raises | Log, skip that provider, continue the run. `AutoPickRun.status = partial`. |
| Zero candidates clear threshold | Write `AutoPickRun` with empty pick list and `status=no_picks`. Admin notified "no picks today." Not an error. |
| DB write fails mid-batch | Single transaction — all picks commit together or none. Run is idempotent on `(run_date, market_type, event_id, selection)`. |
| Admin doesn't approve before game starts | Pick auto-expires: `status=EXPIRED`. Existing live-betting cutoffs apply. |

## Testing Strategy

**Unit tests:**
- `ConfidenceScorer` — fixture-driven; each sub-score in isolation; composition; edge cases (zero edge, negative edge, missing historical data, stale projection, no model confidence). Golden test: the Strider example (9.0 K projection vs 5.5 line → high score).
- `BetSelector` — correlation guard, odds cutoffs, tier assignment by rank, fewer-than-4 cases (0, 1, 2, 3 eligible).
- Each `CandidateProvider` — returns correctly-shaped candidates given mocked source; returns `[]` when projections missing.

**Integration tests:**
- `AutoPickOrchestrator` end-to-end with test DB and mocked feeds: full run produces correct pending bets + audit row; idempotent on re-run.
- Failure injection: one provider raises → run completes with the rest; DB failure → no partial writes.
- Admin approval flow: pending → approve → tier-gated visibility.

**Backtest harness (v1 scope):**
- CLI: `python -m yetai.auto_pick.backtest --start <date> --end <date>`
- Replays historical odds + projections through scorer + selector.
- Reports: hit rate per tier, ROI, score-vs-outcome calibration.
- Used to tune weights and threshold without flying blind. Modeled on the existing `Financials` backtest CLI.

## Rollout Plan

1. **Phase 1 — Foundation:** migrations, `BetCandidate` interface, scorer + selector with unit tests, backtest harness. Run backtest on the last 90 days; confirm calibration.
2. **Phase 2 — Shadow mode:** orchestrator runs daily and writes `auto_pick_runs` + `PENDING_APPROVAL` bets, but admin portal additions are hidden behind a feature flag. Inspect picks manually for ~1 week. Nothing publishes.
3. **Phase 3 — Admin portal live:** unhide approval UI. Real picks start flowing to subscribers post-approval.
4. **Phase 4 — Tuning:** after 2–3 weeks of live data, adjust weights in `scoring_config` based on hit rates. No code changes needed.

## Dependencies to Confirm During Implementation

1. `notification_router` can carry an "admin: picks pending approval" message — verify or add a small admin channel.
2. `performance_tracker` exposes 90-day hit rate per `(market_type, league)` — verify or add a lightweight aggregator.
3. Line movement snapshots exist — verify or add a simple snapshot table populated alongside existing odds ingestion.

If any of these are missing, they become part of Phase 1.

## Open Tuning Parameters

These start at the values below and are adjustable via `scoring_config` after observing live performance:

- Sub-score weights (40 / 20 / 15 / 10 / 10 / 5)
- Score threshold: **65**
- Odds hard cutoffs: `[-300, +400]`
- Daily run time: **9:00 AM ET**
- Max picks per day: **4**
