# Game projections collapse

**Date:** 2026-08-05  
**Status:** Approved for planning  
**Scope:** Frontend only — `GameProjectionsSection`

## Problem

On sport Stat Projections pages, prop tables collapse via a chevron header (`PredictionsTable`). Game projections (`topSection` → `GameProjectionsSection`) stay always expanded, so long slate cards block prop tables until the user scrolls.

## Goals

- Let users minimize the Game projections block the same way they minimize prop tables.
- Keep preference **session-only** (no `localStorage`).
- Keep Game projections **independent** of Show all / Hide all and prop chips.

## Non-goals

- Persisting collapse across reloads
- Wiring Game projections into the prop toolbar
- Visual restyle into a prop-table card shell
- Backend or API changes

## Design

### Behavior

| Item | Choice |
|------|--------|
| Default | Expanded |
| Toggle | Click header (chevron + title) |
| Collapsed content | Hide `GameProjectionsGrid` (summary + game cards); keep title + subtitle |
| Toolbar | No change — Show/Hide all and chips ignore this section |
| Persistence | `useState(true)` only; resets on refresh |
| A11y | Toggle `button` with `aria-expanded` |

### Implementation

- **File:** `frontend/src/components/yetai/GameProjectionsSection.tsx`
- Add local `expanded` state (default `true`).
- Replace static title block with a button matching `PredictionsTable` interaction: `ChevronDown` when open, `ChevronRight` when closed (`lucide-react`).
- Conditionally render `GameProjectionsGrid` when `expanded`.
- Do not change `SportPredictionsPage`, storage keys, or prop-group expand maps.

### Testing

- Manual: toggle open/closed on MLB (or any sport using `GameProjectionsSection`); confirm props still Show/Hide independently; refresh restores expanded.
- No new unit test required unless an existing component test covers this section.

## Alternatives considered

1. **Local state in section (chosen)** — smallest change, matches interaction, independent.
2. **Reuse prop-table card CSS classes** — more visual parity, tighter coupling to table chrome.
3. **Lift state to `SportPredictionsPage`** — useful if toolbar integration were desired; out of scope.
