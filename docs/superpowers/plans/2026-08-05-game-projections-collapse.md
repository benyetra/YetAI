# Game Projections Collapse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add session-only expand/collapse to Game projections, matching prop table chevron UX, without toolbar or localStorage integration.

**Architecture:** Local `useState(true)` in `GameProjectionsSection`. Header becomes a toggle button; `GameProjectionsGrid` renders only when expanded. No parent page or persistence changes.

**Tech Stack:** React client component, lucide-react chevrons, existing `predictions-table-toggle` styles where they fit without wrapping in a prop card.

## Global Constraints

- Session-only collapse (no `localStorage`)
- Independent of Show all / Hide all and prop chips
- Do not wrap Game projections in a prop-table card shell
- Frontend only — single file change

**Spec:** `docs/superpowers/specs/2026-08-05-game-projections-collapse-design.md`

## File map

| File | Role |
|------|------|
| `frontend/src/components/yetai/GameProjectionsSection.tsx` | Add expanded state + toggle header; conditional grid |
| `frontend/src/styles/yetai-design.css` | Only if toggle needs a small non-card layout tweak |

---

### Task 1: Collapsible GameProjectionsSection

**Files:**
- Modify: `frontend/src/components/yetai/GameProjectionsSection.tsx`
- Test: Manual on Stat Projections page (no dedicated unit test file exists)

**Interfaces:**
- Consumes: existing props (`variant`, `data`, `loading`, `isPastDate`, `onAddToSlip`) unchanged
- Produces: same public component API; internal `expanded: boolean` default `true`

- [x] **Step 1: Implement collapse in GameProjectionsSection**

Replace the component body with local expanded state and a chevron toggle header. Keep subtitle visible when collapsed. Conditionally render `GameProjectionsGrid`.

```tsx
'use client';

import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import GameProjectionsGrid, {
  type GameProjectionSlipPick,
  type GameProjectionsVariant,
} from '@/components/yetai/MlbGameProjectionsGrid';
import { gameProjectionRows } from '@/lib/gameProjectionsFromApi';

export default function GameProjectionsSection({
  variant,
  data,
  loading,
  isPastDate,
  onAddToSlip,
}: {
  variant: GameProjectionsVariant;
  data: Record<string, Array<Record<string, unknown>>> | null;
  loading: boolean;
  isPastDate: boolean;
  onAddToSlip?: (pick: GameProjectionSlipPick) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const rows = useMemo(() => gameProjectionRows(variant, data), [variant, data]);

  return (
    <section style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: expanded ? 12 : 0 }}>
        <button
          type="button"
          className="predictions-table-toggle"
          onClick={() => setExpanded((prev) => !prev)}
          aria-expanded={expanded}
        >
          {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
          <h2 className="type-section-title" style={{ margin: 0 }}>
            Game projections
          </h2>
        </button>
        <p className="dim" style={{ fontSize: 12, margin: '4px 0 0' }}>
          Win-probability and projected score by ML model
        </p>
      </div>
      {expanded && (
        <GameProjectionsGrid
          rows={rows}
          loading={loading}
          isPastDate={isPastDate}
          variant={variant}
          onAddToSlip={onAddToSlip}
        />
      )}
    </section>
  );
}
```

- [x] **Step 2: Type-check**

Run: `cd frontend && npm run type-check`  
Expected: exit 0 — PASS

- [ ] **Step 3: Manual verify checklist**

1. Open MLB Stat Projections — Game projections expanded by default  
2. Click header — grid hides; title + subtitle remain  
3. Click again — grid returns  
4. Show all / Hide all on props does not change Game projections  
5. Refresh — Game projections expanded again  

- [ ] **Step 4: Commit (only if user requests)**

```bash
git add frontend/src/components/yetai/GameProjectionsSection.tsx \
  docs/superpowers/specs/2026-08-05-game-projections-collapse-design.md \
  docs/superpowers/plans/2026-08-05-game-projections-collapse.md
git commit -m "$(cat <<'EOF'
feat: allow collapsing game projections on stat pages

Match prop-table chevron UX with session-only expand state,
independent of Show/Hide all.
EOF
)"
```
