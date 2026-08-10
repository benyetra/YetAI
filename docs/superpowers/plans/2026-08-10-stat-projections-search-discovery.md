# Stat projections search + discovery Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** Add player-name search on all stat projection pages and a best-edges discovery strip for NBA, WNBA, and MLB.

**Architecture:** Shared helpers select/filter rows; `SportPredictionsPage` owns search state and renders an optional discovery strip; sport pages pass discovery group configs.

**Tech Stack:** Next.js / React, existing PredictionsTable + yetai-design.css

## Global Constraints

- Client-side only; no API changes.
- Positive edge only (`edge > 0` / `k_edge > 0`); not absolute edge.
- Discovery limit = 3 per group.
- Search applies to all sports with player prop tables.

---

### Task 1: Discovery helpers + tests

**Files:**
- Create: `frontend/src/lib/propDiscovery.ts`
- Create: `frontend/src/lib/propDiscovery.test.ts`

- [ ] Helpers: `rowPersonName`, `rowMatchesPlayerSearch`, `selectTopPositiveEdge`, `selectTopByNumericField`, types for `DiscoveryGroupConfig`
- [ ] Unit tests for ranking and search match
- [ ] Commit

### Task 2: BestEdgesDiscovery UI + CSS

**Files:**
- Create: `frontend/src/components/yetai/BestEdgesDiscovery.tsx`
- Modify: `frontend/src/styles/yetai-design.css`

- [ ] Render groups with compact rows (name, team, opp, proj/line, edge or value, pick)
- [ ] Styles under `.predictions-discovery*`
- [ ] Commit

### Task 3: Wire SportPredictionsPage

**Files:**
- Modify: `frontend/src/components/yetai/SportPredictionsPage.tsx`

- [ ] Search input in toolbar; filter rows before table render
- [ ] Accept `discoveryGroups`; render strip above toolbar when data qualifies
- [ ] Commit

### Task 4: Sport configs

**Files:**
- Modify: `frontend/src/app/predictions/nba/page.tsx`
- Modify: `frontend/src/app/predictions/wnba/page.tsx`
- Modify: `frontend/src/app/predictions/mlb/page.tsx`

- [ ] Pass discovery group configs per approved design
- [ ] Commit

### Task 5: Verify

- [ ] `npx jest --testPathPatterns=propDiscovery`
- [ ] `npm run type-check`
