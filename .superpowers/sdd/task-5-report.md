## Task 5 Report: Chrome, OG, H2H/drafts polish + gates

Status: complete

### Implemented
- Added the StadiumMark micro-mark to the League Vault nav brand and switched active nav underline to gold.
- Enriched the footer with a quiet archive note and StadiumMark treatment.
- Reworked the OG image with a deeper field-green gradient, gold kicker, larger title, field-line geometry, and a JSX/CSS geometric gold cup.
- Highlighted H2H diagonal self cells and winning-record cells.
- Highlighted the round 1 first-overall draft row and kept pending draft copy calm.

### Gates
- `npm run type-check` - passed
- `npm run test:unit -- --testPathPatterns=vault-` - passed
- `PLAYWRIGHT_HTML_OPEN=never npx playwright test tests/fantasy-happy-path.spec.ts --project=chromium --reporter=line` - passed
- `npm run lint` - exit code 0; Next emitted the existing deprecated `next lint` / older ESLint message
- `npm run test:ci` - passed

### Notes
- No push or PR performed per request.

---

## Final review fixes (whole-branch pass)

Status: complete

### Fixed
1. **Trophy podium DOM order** (`trophies/page.tsx`): `podiumSlots` now renders 1→2→3 for mobile and screen-reader order. Desktop layout unchanged via existing `grid-template-areas: 'second first third'`.
2. **Reduced motion** (`vault.css`): Added `@media (prefers-reduced-motion: reduce)` to disable `vault-rise`, `vault-podium-entrance`, and `vault-shimmer` animations; static gold text for shimmer; removed hover/transition motion on interactive vault cards and CTAs.

### Gates
- `npm run type-check` — passed
- `npm run test:unit -- --testPathPatterns=vault-` — passed (8 tests)

### Notes
- Commit: `fix(league-vault): podium DOM order and reduced-motion`
- No push or PR performed per request.
