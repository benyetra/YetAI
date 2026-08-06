# League Vault UI Showcase Plan

**Goal:** Make the public vault sites feel like a paid fantasy-league showcase — trophy room energy, championship highlights, motion, and memorable imagery — without changing API contracts or pilot non-goals.

**Branch:** `cursor/league-vault-ui-showcase-6739`  
**Base:** `main` @ `295bd0c`

## Visual direction

**Championship media guide** (not purple, not cream/terracotta, not broadsheet):

| Token | Value | Role |
|-------|--------|------|
| `--vault-ink` | `#0c1210` | Text |
| `--vault-paper` | `#eef3ef` | Cool field-adjacent paper |
| `--vault-field` | `#0f3d2e` | Deep turf |
| `--vault-gold` | `#c6a035` | Titles / #1 / accents |
| `--vault-accent` | `#147a5f` | Links / active |
| `--vault-muted` | `#5c6b63` | Secondary |

Fonts stay **Newsreader** (display) + **Source Sans 3** (UI).

Imagery: **inline SVG illustrations** (trophy cup, podium, medal, stadium lights) under `frontend/src/components/vault/illustrations/` — no external stock photos, no emoji.

Motion (minimum 3):
1. Hero rise + soft gold shimmer on reigning champ
2. Dynasty rail stagger + hover lift
3. Trophy/medal entrance on Trophy Room

## Global Constraints

1. Frontend-only for this plan (no backend / OpenAPI / Alembic).
2. Preserve all existing vault routes and data wiring (`fetchVaultSnapshot`, `vaultPath`, manager links).
3. Follow design rules: one composition on home hero; brand/league name is hero-level; no cards in hero; cards only when they hold interaction; no purple theme; no cream+#terracotta; no broadsheet hairlines; no emoji; avoid rounded-full pill clusters and glow spam.
4. Mobile-first; sticky nav must remain usable.
5. Do not introduce new npm dependencies unless already in `package.json` (lucide-react is OK if already used by vault; prefer custom SVG).
6. Before commit: `cd frontend && npm run type-check && npm run test:unit -- --testPathPatterns=vault-`.
7. Commit after each task on branch `cursor/league-vault-ui-showcase-6739`.
8. Accessibility: decorative SVGs `aria-hidden`; meaningful text remains in DOM (not only in images).

---

## Task 1: Illustration kit + design tokens

**Files:**
- Create `frontend/src/components/vault/illustrations/TrophyCup.tsx`
- Create `frontend/src/components/vault/illustrations/Podium.tsx`
- Create `frontend/src/components/vault/illustrations/Medal.tsx`
- Create `frontend/src/components/vault/illustrations/StadiumMark.tsx`
- Create `frontend/src/components/vault/illustrations/index.ts`
- Update `frontend/src/app/vault/vault.css` (tokens + shared utility classes only; page layouts come later)

**Requirements:**
1. Each illustration is a React component returning an `<svg>` with `aria-hidden="true"` and a `className` prop.
2. TrophyCup: classic cup with handles, gold fill + dark stroke, viewBox ~120x140.
3. Podium: 3 steps (2nd / 1st / 3rd heights), gold rim on #1.
4. Medal: circular medal with ribbon, accepts optional `rank` 1|2|3 for fill (gold/silver/bronze).
5. StadiumMark: simple floodlight / arch mark for chrome accents.
6. CSS: replace/extend root variables to the table above; add utility classes:
   - `.vault-gold-text`
   - `.vault-rank-1` / `.vault-rank-2` / `.vault-rank-3` (row highlight backgrounds)
   - `.vault-shimmer` (subtle gold gradient animation for champ name)
   - `.vault-illust` (max-width constraints for SVGs)
7. Keep existing structural classes (`.vault-header`, `.vault-table`, etc.) working; retune colors to new tokens.
8. Add `@keyframes vault-shimmer` and keep `vault-rise`.

**Tests:** none required beyond type-check (SVG components).

**Commit:** `feat(league-vault): championship illustration kit and design tokens`

---

## Task 2: Home hero + explore showcase

**Files:**
- Update `frontend/src/app/vault/[slug]/page.tsx`
- Update `frontend/src/components/vault/VaultChrome.tsx` (DynastyBar polish)
- Update `frontend/src/app/vault/vault.css` (hero / dynasty / explore styles)

**Requirements:**
1. Home first viewport = one composition: league name (hero), short kicker (Est. · seasons), reigning champion spotlight with TrophyCup visual, one CTA group (links to Trophy Room + Record Book), dynasty timeline.
2. Do **not** put stats strips, schedule, or secondary marketing in the hero.
3. Champion block: large TrophyCup beside/above champ name; champ name uses `.vault-shimmer` / gold treatment; link to manager page preserved.
4. DynastyBar: richer cells, gold border for most recent completed champ season, stagger animation delays, hover lift; keep manager links.
5. Explore section below hero: interactive destination tiles (allowed as cards because they are the interaction). Each tile: short label + one-line tease + optional small illustration (Medal / StadiumMark). Include existing destinations (Trophies, Records, Managers, Seasons, H2H, Moves, Draft when available).
6. Motion: hero rise, shimmer, dynasty stagger (already listed).

**Tests:** type-check + vault unit tests still pass.

**Commit:** `feat(league-vault): championship home hero and explore tiles`

---

## Task 3: Trophy Room spectacle

**Files:**
- Update `frontend/src/app/vault/[slug]/trophies/page.tsx`
- Update `frontend/src/app/vault/vault.css`

**Requirements:**
1. Page header with Podium or TrophyCup visual + “Trophy Room” title.
2. **Reigning / title leaders podium:** top 3 title-holders as a visual podium (1st center tallest) using Podium illustration + names/links + title counts. If fewer than 3 champions historically, show what’s available.
3. **Season chronicle:** replace plain table vibe with a vertical timeline or highlighted rows — champion gets gold accent + Medal; runner-up silver; last place muted. Keep links. “In progress” seasons stay muted without fake medals.
4. Keep Titles leaderboard but style rank-1/2/3 rows with `.vault-rank-*`.
5. Entrance animation on podium block.

**Tests:** type-check.

**Commit:** `feat(league-vault): trophy room podium and season chronicle`

---

## Task 4: Records, managers, seasons highlights

**Files:**
- Update `frontend/src/app/vault/[slug]/records/page.tsx`
- Update `frontend/src/app/vault/[slug]/managers/page.tsx`
- Update `frontend/src/app/vault/[slug]/managers/[managerSlug]/page.tsx`
- Update `frontend/src/app/vault/[slug]/seasons/[year]/page.tsx`
- Update `frontend/src/app/vault/vault.css` as needed

**Requirements:**
1. Records: Career section header with Medal; first/highest rows get subtle gold left-border highlight; values stay tabular.
2. Managers index: sort by titles then wins; show title count with gold medal mark when titles > 0; highlight top title holder row.
3. Manager detail: if titles > 0, show TrophyCup badge in header; champion seasons marked with gold star treatment (text/CSS, not emoji).
4. Season detail: #1 standing row uses `.vault-rank-1`; playoff week headings get gold accent.
5. Do not add new data fetches.

**Tests:** type-check + vault unit tests.

**Commit:** `feat(league-vault): highlight records managers and season leaders`

---

## Task 5: Chrome, OG, H2H/drafts polish + gates

**Files:**
- Update `frontend/src/components/vault/VaultChrome.tsx`
- Update `frontend/src/app/vault/[slug]/opengraph-image.tsx`
- Update `frontend/src/app/vault/[slug]/h2h/page.tsx` (light polish)
- Update `frontend/src/app/vault/[slug]/drafts/[year]/page.tsx` (light polish)
- Update `frontend/src/app/vault/vault.css`
- Optionally `frontend/tests/unit/vault-helpers.test.ts` if helpers added

**Requirements:**
1. Nav: StadiumMark micro-mark beside “League Vault”; active link uses gold underline.
2. Footer: slightly richer but still quiet.
3. OG image: deeper field-green gradient, gold “League Vault” kicker, larger title, optional “🏆” **forbidden** — use geometric gold cup shape via JSX/CSS boxes if possible inside ImageResponse (no external SVG files).
4. H2H: highlight diagonal self cells; winning record cells slight green tint when wins > losses (inline style or class).
5. Drafts: round-1 first overall row gold highlight; pending state keeps calm copy.
6. Run: `npm run type-check`, `npm run test:unit -- --testPathPatterns=vault-`, and `PLAYWRIGHT_HTML_OPEN=never npx playwright test tests/fantasy-happy-path.spec.ts --project=chromium --reporter=line`.

**Commit:** `feat(league-vault): chrome OG and matrix polish`

---

## Out of scope

- Subdomain DNS, Stripe, commissioner UI, themes picker, weekly sync
- Backend snapshot changes
- Replacing fonts with Inter/Roboto
