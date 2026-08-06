# League Vault Pilot — Observation Log

Append entries during P4 (ship & watch). Do **not** ask managers if they like it — watch what they do.

## Ship checklist

- [x] Code merged to `main` (#45–#50)
- [x] Live snapshots 200: `GET /api/vault/mikes-hard` and `league-838295`
- [x] Path sites 200: `https://yetai.app/vault/mikes-hard` and `/vault/league-838295`
- [x] `prod_verify_pilot.py --skip-db --api-url https://api.yetai.app` exit 0
- [ ] `compute_pilot.py` — **records still empty** (0 in both snapshots); run against prod `DATABASE_URL`
- [ ] GH Actions Alembic still queued (Railway **git** deploy is what ships API); run **Database Migrations** workflow_dispatch if schema_align needed
- [ ] Wildcard `*.yetai.app` on Vercel; `api.yetai.app` still Railway (`mikes-hard.yetai.app` does not resolve yet)
- [ ] Paste path or subdomain into iMessage — OG card looks right
- [ ] Post to each group chat with **no** “product test” framing
- [ ] Note ship timestamp below

### Live status (2026-08-06 ~18:40 UTC)

| Check | Result |
|-------|--------|
| Snapshots both slugs | ✅ 200 |
| Meta / stats | ✅ 200 |
| `prod_verify` API | ✅ |
| Privacy (`platform_user_id` / SWID) | ✅ not leaked |
| Mike's Hard | 6 seasons (2021–2026), 13 managers, 0 records, drafts present |
| ESPN 838295 | 10 seasons (2017–2026), 14 managers, 0 records, drafts present |
| Frontend `/vault/{slug}` | ✅ 200 |
| `*.yetai.app` subdomain | ❌ DNS NXDOMAIN |
| Record book | ❌ empty until `compute_pilot.py` |

**Shipped at (path URLs):** 2026-08-06 ~18:40 UTC  
**Links (share these until DNS):**  
- Sleeper: https://yetai.app/vault/mikes-hard  
- ESPN: https://yetai.app/vault/league-838295  
**Subdomain (after DNS):**  
- https://mikes-hard.yetai.app  
- https://league-838295.yetai.app  

---

## Engagement log

| When | League | Signal | Notes |
|------|--------|--------|-------|
| | | unprompted screenshot / argument / feature ask / forward / silence | |

### Thresholds (from Pilot PRD §9)

**Build the business if:**
- Unprompted engagement (screenshots, arguments, feature asks)
- ≥70% of each league’s managers visit within 7 days
- Median ≥4 pages / session (use `/api/vault/{slug}/stats` path diversity + totals)
- Anyone returns in week 2
- ⭐ Someone forwards outside the league or asks for another league
- Unprompted “$5 is worth it”

**Stop / reshape if:**
- Polite ack then silence
- One-and-done visits
- ESPN unusable (already cleared in P0)
- Manual identity correction > ~30 min / league
- Typically <3 seasons of history

---

## Manual fixes log

| Date | League | Issue | Time spent | Fix |
|------|--------|-------|------------|-----|
| 2026-08-06 | — | Deploy blocked: events table exists unstamped | — | #46 idempotent migration |
| 2026-08-06 | both | Snapshot 500: score column name drift | — | #46 align to `team_a_score` |
| 2026-08-06 | — | Backend CI black fail on `main.py` | — | #47 |
| 2026-08-06 | both | Snapshot 500: draft schema drift (`status`, `pick`, `platform_roster_id`) | — | #48–#50 |
| 2026-08-06 | both | Record book empty | — | pending `compute_pilot.py` on prod |

**Identity correction time (deliverable):**  
- Sleeper: _min_  
- ESPN: _min_  

---

## Go / no-go (fill after 2–3 weeks)

**Decision:** go / no-go / reshape  

**Reasoning:**  

**Next action:**  
