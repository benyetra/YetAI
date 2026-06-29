# YetiWatch — Projection News Layer (WNBA)
### Product Requirements Document

**Working title:** YetiWatch (a YetAI module)
**Author:** Bennett Yetra
**Status:** Draft v0.4
**Last updated:** June 28, 2026

---

## 1. Summary

YetiWatch is a news-enrichment layer inside **YetAI**. Through the pre-game window, it scans news / injury reports / lineup feeds for every player in the WNBA projection slate, and **synthesizes an original summary from sentiment and signals aggregated across multiple sources** — classifying anything material (rest, minutes caps, rotation changes, teammate availability, etc.) and writing a concise **string-based `news` column** onto each projection row.

It runs **immediately before each projection run, multiple times pre-game**, so the projection engine always consumes the freshest signals — making projections more accurate — while the human-readable string sits next to each projection so the user sees the context that drove the number.

One pass, two outputs:
1. **Feeds the projection model** structured signals (status, minutes delta, usage delta, role change) so projections reflect the latest reality.
2. **Displays a `news` string** per row so the user understands *why* a projection moved.

---

## 2. Problem Statement

Projections go stale the moment news breaks:

- A player is held out for **rest / load management** — a real risk in the WNBA's short rotations and dense back-to-back schedule.
- A player returns on a **minutes restriction**, quietly capping output.
- A **rotation / starter change** shifts usage and minutes.
- A **teammate ruled out** spikes the remaining players' usage.
- **National-team / overseas commitments** pull players out of availability windows.
- **Blowout / pace** dynamics pull starters early or suppress totals.

Much of this lands **close to tip-off** (late scratches, final injury-report updates). If the projection engine doesn't see it before it runs, every downstream number is wrong. YetiWatch injects the latest synthesized read *into* the run and *onto* the row, and refreshes as game time approaches.

---

## 3. Goals & Non-Goals

### Goals
1. Run a WNBA news scan immediately before each projection run, covering the full slate, with **multiple refreshes through the pre-game window** that intensify toward tip-off.
2. **Synthesize an original summary** from multi-source sentiment/signals — not redistributed source text.
3. Emit a **string-based `news` column** per projection row — concise, timestamped, impact-tagged.
4. Emit a **parallel structured signal** the projection engine ingests for accuracy.
5. Catch material developments (rest, minutes cap, rotation, teammate-out, status changes) with cross-source confidence labeling.

### Non-Goals (v1)
- Not a replacement for the projection model — it's an input layer.
- Not a generic news reader; every item is anchored to a projected subject.
- Not push-alerting (a possible later layer, not v1).
- No per-user / per-bet scoping — enrichment runs for all projections.

---

## 4. Target User

**Primary:** YetAI users viewing WNBA projections who want numbers that already reflect breaking news, with the news context shown inline. The layer is bet-agnostic — it enriches the projections themselves.

---

## 5. Key Concepts

| Term | Definition |
|---|---|
| **Slate** | The set of WNBA games/players YetAI is projecting for a given run. |
| **Projection row** | One projected line for a (player, game) — the row the `news` column attaches to. |
| **Subject** | A monitorable entity: player, team, or game. |
| **Signal** | A discrete classified development ("Player ruled OUT — rest"), with type, confidence, timestamp. |
| **Synthesis** | The original summary YetiWatch generates by aggregating sentiment/signals across multiple sources. |
| **`news` column** | The string written to each projection row: short synthesized summary + impact tag + timestamp. |
| **Structured signal payload** | The machine-readable companion the projection engine consumes (status, minutes delta, usage delta, role change). |

---

## 6. Pipeline & Timing *(core architectural requirement)*

YetiWatch is an **upstream dependency of the projection job**, not a parallel service.

```
            [WNBA Slate]
                 │
                 ▼
       (1) NEWS JOB  ◀── runs immediately before EACH projection run
        - for every player in the slate
        - aggregate signals/sentiment across multiple sources
        - synthesize original summary + impact tag
        - write `news` string + structured payload per subject
                 │
                 ▼
       (2) PROJECTION JOB
        - consumes structured signals
        - outputs projections WITH the news column attached
                 │
                 ▼
       YetAI Projections Page (news column visible per row)
```

**Timing rules**
- The news job runs **multiple times through the pre-game window**, each run immediately preceding a projection run.
- **Cadence tightens toward tip-off** — because news often breaks late, refreshes are periodic early, more frequent in the final stretch, with a **near-lock run** as close to tip as feasible.
- Runs align to the latest available info: **after WNBA official injury-report releases** and lineup-lock windows.
- Each run **re-synthesizes from the latest multi-source state**; the newest synthesis wins, and the column's **as-of timestamp** reflects the last run so staleness is always visible.

---

## 7. Functional Requirements

### 7.1 Entity Resolution (WNBA)
- Resolve every slate player/team to canonical `player_id` / `team_id`.
- Maintain a WNBA registry (12 teams, ~12-player rosters) with fuzzy matching + manual-correct path.
- Attach game context: opponent, home/away, B2B flag, national TV, schedule density.

### 7.2 Multi-Source News Ingestion (WNBA)
- Pull from multiple sources (see §8) on each run.
- Normalize to candidate items: `source`, `timestamp`, `subjects`, `raw_text`.
- Dedupe near-identical items across sources before synthesis.

### 7.3 Cross-Source Synthesis, Signal Typing & Impact
For each slate subject, aggregate all relevant items and produce one synthesized read:
1. **Relevance filter** — concerns a slate subject + the upcoming game? (drop stale / wrong-game).
2. **Cross-source aggregation** — combine sentiment/signals across sources. **Corroboration across multiple sources raises confidence; conflicting sources lower it.** The output is an *original synthesis*, never a passthrough of any single source.
3. **Signal typing** — classify into the WNBA taxonomy (§7.4).
4. **Production-impact assessment** — relative to the player's expected output:
   - `direction`: production ↑ / ↓ / neutral
   - `magnitude`: low / medium / high
   - `drivers`: structured fields — `status`, `minutes_delta`, `usage_delta`, `role_change`
   - `rationale`: one-line plain English
   - `confidence`: 0–1 from source corroboration × signal clarity

### 7.4 WNBA Signal Taxonomy

| Signal | Typical production impact |
|---|---|
| Rest / load management / DNP-rest | strong ↓ (often full DNP) |
| Injury status change (Q/D/OUT, in-game) | ↓, or ↑ for teammates |
| Minutes restriction / cap (return from injury) | ↓ output |
| Increased role / usage bump | ↑ |
| Rotation / starter change | direction depends |
| Teammate availability change | inverse-↑ remaining players' usage |
| National-team / overseas duty / availability window | possible DNP |
| Blowout / pace / garbage-time risk | ↓ starter minutes, shifts totals |
| Foul-trouble / ejection (in-game) | ↓ minutes-dependent output |
| Trade / roster move | may void or reshape the row |
| Coaching change / scheme shift | broad |

### 7.5 `news` Column Composition (string-based)
- Compose a **short, column-friendly synthesized string** per projection row:
  - `<synthesized summary> [impact tag] <as-of timestamp>`
  - The string is **original synthesis derived from multi-source sentiment — not redistributed source text.**
  - Empty/neutral state written explicitly (e.g., `No material news. 3:00p ET`) so blank ≠ "not checked".
- One line, impact tag bracketed, time always present.
- Overwritten on each pre-game run with the latest synthesis.
- Emit the **structured signal payload** alongside (consumed by the projection engine; see 7.6).

### 7.6 Projection-Engine Consumption
- The projection job reads the **structured payload** (preferred — reliable) to adjust minutes / usage / availability inputs.
- The `news` string is the human-facing mirror of that same payload, persisted on the row.
- If the engine can only read the column, it must be able to parse the string; the structured field exists to avoid that fragility.

### 7.7 (Later) Alerting
- Optional Phase-2 push (Discord/in-app) for high-severity slate changes. Not required for v1.

---

## 8. Data Sources

Aggregated across tiers; corroboration across them drives confidence:

1. **Official** — WNBA official injury report (scheduled releases), official team lineup posts.
2. **Verified beat writers / insiders** — established WNBA reporters.
3. **Aggregators / sports data APIs** — free/low-cost feeds for status, lineups, schedule (consistent with prior bot work).
4. **Community / rumor** — folded into sentiment at low weight.

> **Redistribution:** YetiWatch publishes an **original synthesized summary** derived from aggregated multi-source sentiment — it does not republish source text — so source ToS / redistribution is not a blocking concern.

---

## 9. AI / ML Approach
- **LLM-based cross-source synthesis + impact classification** (Bedrock-friendly), with **WNBA-tuned prompt templates** that encode what matters (minutes, usage, rotation, rest).
- Inputs are the deduped multi-source items for a subject; output is an **original synthesized summary** plus **structured JSON** (`direction`, `magnitude`, `drivers`, `confidence`) that drives both the projection inputs and the display string.
- **Confidence reflects corroboration:** agreement across sources raises it, contradiction lowers it.
- Lightweight **pre-filter** (entity/keyword match) before the LLM to control cost/latency — important since this runs inline before every projection run, multiple times pre-game.
- **Calibration loop:** compare synthesized reads against actual results to tune confidence and the projection engine's response weighting.

---

## 10. UX — `news` Column Examples

Illustrative synthesized strings as they'd appear on the projections page:

| Player | Proj | `news` |
|---|---|---|
| Player A | 18.2 pts | `Min cap ~22 on return from ankle; usage steady. [prod ↓ med] 5:40p ET` |
| Player B | 15.6 pts | `Star teammate out (rest, B2B); usage projects up. [prod ↑ med] 4:12p` |
| Player C | 20.1 pts | `Full participant, no concern across reports. [neutral] 3:00p` |
| Player D | 11.4 pts | `Questionable (knee), reports mixed, no ruling yet. [unknown] 2:30p` |

Principles: one line, bracketed impact tag, timestamp always present, explicit neutral/unknown states, color-coding optional on the page.

---

## 11. MVP Scope & Phasing

**Phase 1 (MVP) — WNBA, inline with projections**
- WNBA entity resolution across the slate.
- News job as upstream pipeline step, multiple pre-game runs.
- Multi-source aggregation + original synthesis.
- Core signals: rest, injury status, minutes cap, teammate-out, rotation change.
- `news` string column + structured payload feeding projections.

**Phase 2 — Depth**
- Add pace/blowout, national-team/overseas, foul-trouble.
- Confidence calibration loop; projection-accuracy lift measurement.
- Optional push alerting on high-severity changes.

**Phase 3 — Multi-sport reuse + in-game**
- Generalize the layer to other YetAI sports (NBA, MLB pitching/weather, NFL).
- In-game monitoring for news landing after lock.

---

## 12. Success Metrics
- **Projection-accuracy lift:** error reduction on rows where news was present, vs. a no-news baseline (the headline metric).
- **Freshness:** median age of the `news` string at projection-run time (want it captured after the latest injury report / near lock).
- **Coverage:** % of slate rows with a non-empty, current `news` value.
- **Precision:** % of material-tagged items that were genuinely material.
- **Recall:** % of material pre-run events caught before the projection run.
- **Direction accuracy:** % of production-impact calls correct in hindsight.

---

## 13. Risks & Open Questions
- **Inline latency vs. cost** — multiple LLM synthesis passes pre-game must stay fast/cheap; the pre-filter is the mitigation.
- **Conflicting sources** — synthesis must handle disagreement gracefully and express it via confidence rather than picking a side blindly.
- **Late-breaking-at-tip news** — the final pre-game run must fire as close to lock as feasible; anything after lock is Phase-3 in-game territory.
- **Entity-matching errors** — messy name strings → wrong/missing column values; needs a solid registry + fuzzy match.
- **String vs structured** — engine should consume the structured payload, not parse the string; keep them in sync.

---

## 14. Responsible Use Note

YetiWatch is a **projection-accuracy and information** layer. It enriches projections and shows synthesized news context; it does not place bets, guarantee outcomes, or instruct action.
