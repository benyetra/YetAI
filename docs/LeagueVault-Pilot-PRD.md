# League Vault Pilot PRD

**Two real league history sites, on real infrastructure, to decide whether this is a business**

| | |
|---|---|
| **Status** | Phase 3 in progress — public API + `/vault/[slug]` pages + OG + middleware on this branch |
| **Author** | Bennett |
| **Date** | 2026-08-06 |
| **Supersedes for now** | `LeagueVault-PRD.md` (commercial product — parked, not cancelled) |
| **Scope** | Bennett's Sleeper league + ESPN league `838295` |
| **Target** | Live before Week 1 of the 2026 NFL season |

## Pilot leagues

| League | Platform | Slug (provisional) | Seasons |
|--------|----------|--------------------|---------|
| Mike's Hard Fantasy Football | Sleeper | `mikes-hard` | 2021–2026 (12 teams) |
| ESPN `838295` | ESPN | `league-838295` | 2017–2026 (12→10 teams) |

## Phases

| Phase | Scope | Status |
|-------|--------|--------|
| **P0** | API spike + fixtures | ✅ |
| **P1** | `lv_*` schema, ingest, normalizer, sync CLI | ✅ |
| **P2** | Identity overrides, all-play/luck, record book, snapshot JSON | ✅ |
| **P3** | Wildcard DNS, middleware, `/vault/[slug]` pages, OG images, mobile, public API | ✅ code on branch — DNS/Vercel wildcard still manual |
| **P4** | Ship links to group chats; go/no-go | Planned |

## P3 deliverables (this branch)

| Piece | Location |
|--------|----------|
| Public API | `GET /api/vault/{slug}`, `GET /api/vault/{slug}/meta` — no auth, Cache-Control, PII guard |
| CORS | `allow_origin_regex` for `https://*.yetai.app` |
| Middleware | Subdomain → `/vault/{slug}` rewrite; reserved hosts skipped; matcher allows `robots.txt` |
| Pages | Home, trophies, records, managers (+ detail), seasons (+ year), drafts, transactions, H2H |
| OG image | `vault/[slug]/opengraph-image.tsx` via `next/og` |
| Design | Editorial media-guide shell (Newsreader + Source Sans 3), mobile-first |

### Still manual ops

1. Add wildcard `*.yetai.app` CNAME → Vercel; confirm `api.yetai.app` still points at Railway.
2. Add wildcard domain on the Vercel project.
3. Ensure prod `lv_sites.is_public=true` after re-sync (normalizer now defaults public).
4. Run `compute_pilot.py` so records/all-play exist before sharing.

## Non-goals (binding)

No Stripe, no self-serve onboarding, no commissioner admin UI, no themes, no auth on vault pages, no weekly automated sync.

## Ops

```bash
cd backend
PYTHONPATH=. python3 scripts/league_vault/sync_pilot.py
PYTHONPATH=. python3 scripts/league_vault/compute_pilot.py \
  --overrides scripts/league_vault/seed_overrides.json

# local preview (no DNS): http://localhost:3000/vault/mikes-hard
```
