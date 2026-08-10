# Player search + best-edges discovery (stat projections)

**Date:** 2026-08-10  
**Status:** Approved for implementation

## Problem

Stat projection pages make it hard to (1) find a specific player across long prop tables and (2) quickly spot the best +edge parlay legs without scanning every board.

## Goals

1. **Player-name search** on all sport stat projection pages — filter player prop tables by name.
2. **Best-edges discovery strip** near the top of the page (above prop tables, after game slate / accuracy) for:
   - **WNBA / NBA:** top 3 rows per prop stat with `edge > 0`, ranked by edge descending.
   - **MLB:** top 3 strikeout rows with `k_edge > 0`; top 3 hit chances by highest `projected_hits`.
3. NFL/NHL: search only (no discovery strip in this change).

## Non-goals

- Reordering rows inside prop tables.
- API / ETL changes.
- Discovery for NFL/NHL in this pass.

## Design

### Search

- Text input in the shared prop toolbar on `SportPredictionsPage`.
- Case-insensitive substring match against person-name fields on each row (`player_name`, `pitcher_name`, `batter_name`, `goalie_name`, `qb_player_name`, `kicker_player_name`).
- AND with existing “Top plays only” filter.
- Empty match → table empty message “No players match.”

### Discovery strip

- Optional `discoveryGroups` prop on `SportPredictionsPage`.
- Client-side selection from existing prediction payload.
- Per group: up to 3 rows; hide group if zero qualifiers; hide strip if all groups empty.
- Display: player, team, opponent, key projection/line (when present), signed edge or proj hits, pick when present.

## Ranking rules

| Sport | Group | Qualifier | Order |
|-------|-------|-----------|-------|
| NBA/WNBA | Each prop board | `edge > 0` | edge desc |
| MLB | Strikeouts | `k_edge > 0` | k_edge desc |
| MLB | Hit chances | any with `projected_hits` | projected_hits desc |

## Files (expected)

- `frontend/src/lib/propDiscovery.ts` (+ tests)
- `frontend/src/components/yetai/BestEdgesDiscovery.tsx`
- `frontend/src/components/yetai/SportPredictionsPage.tsx`
- `frontend/src/app/predictions/{nba,wnba,mlb}/page.tsx`
- `frontend/src/styles/yetai-design.css`
