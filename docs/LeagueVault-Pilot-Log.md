# League Vault Pilot — Observation Log

Append entries during P4 (ship & watch). Do **not** ask managers if they like it — watch what they do.

## Ship checklist

- [x] Code merged to `main` (#45–#53)
- [x] Live snapshots 200 + records populated (auto-compute)
- [x] Path sites 200: `https://yetai.app/vault/mikes-hard` and `/vault/league-838295`
- [x] `prod_verify_pilot.py --skip-db --api-url https://api.yetai.app` exit 0
- [ ] Wildcard `*.yetai.app` on Vercel; `api.yetai.app` still Railway
- [ ] Paste path URL into iMessage — OG card looks right
- [ ] Post to each group chat with **no** “product test” framing
- [x] Note ship timestamp below

### Live status (2026-08-06)

| Check | Result |
|-------|--------|
| Snapshots both slugs | ✅ 200 |
| Record book | ✅ 35 (Sleeper) / 37 (ESPN) |
| All-play on teams | ✅ |
| Privacy | ✅ |
| Frontend path URLs | ✅ |
| `*.yetai.app` subdomain | ❌ DNS NXDOMAIN |
| ESPN quoted name / email managers | polish PR heals on GET |
| Reigning champ | last completed season (not in-progress 2026) |

**Shipped at (path URLs):** 2026-08-06  
**Share now:**  
- https://yetai.app/vault/mikes-hard  
- https://yetai.app/vault/league-838295  

---

## Engagement log

| When | League | Signal | Notes |
|------|--------|--------|-------|
| | | unprompted screenshot / argument / feature ask / forward / silence | |

### Thresholds (from Pilot PRD §9)

**Build the business if:** unprompted engagement; ≥70% managers visit in 7d; median ≥4 paths; week-2 return; outward share; willingness to pay.

**Stop / reshape if:** polite silence; one-and-done; identity correction ≫ 30 min/league.

---

## Manual fixes log

| Date | League | Issue | Fix |
|------|--------|-------|-----|
| 2026-08-06 | — | Deploy/schema drift | #46–#53 |
| 2026-08-06 | both | Empty records | auto-compute on GET |
| 2026-08-06 | ESPN | Quoted name / emails | branding heal |

**Identity correction time:** Sleeper _min_ / ESPN _min_ (email→local-part auto)

---

## Go / no-go (fill after 2–3 weeks)

**Decision:**  

**Reasoning:**  

**Next action:**  
