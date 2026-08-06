# League Vault Pilot — Observation Log

Append entries during P4 (ship & watch). Do **not** ask managers if they like it — watch what they do.

## Ship checklist

- [x] Code merged to `main` (#45)
- [ ] Merge deploy unblocker (#46) — idempotent `lv_vault_events` + matchup score column align
- [ ] Railway Alembic + API deploy green after #46
- [ ] Confirm live snapshots: `GET /api/vault/mikes-hard` and `league-838295` return 200
- [ ] `compute_pilot.py` (records + all-play) if `records` empty in snapshot
- [ ] `prod_verify_pilot.py --api-url https://api.yetai.app` exit 0
- [ ] Wildcard `*.yetai.app` on Vercel; `api.yetai.app` still Railway
- [ ] Paste `https://mikes-hard.yetai.app` into iMessage — OG card looks right
- [ ] Same for ESPN slug subdomain
- [ ] Post to each group chat with **no** “product test” framing
- [ ] Note ship timestamp below

### Live status (2026-08-06)

| Check | Result |
|-------|--------|
| `#45` merge | ✅ |
| Railway deploy after `#45` | ❌ Alembic `DuplicateTable: lv_vault_events` |
| `GET .../meta` both slugs | ✅ 200 (data already in prod from P1 ingest) |
| `GET .../snapshot` | ❌ 500 — `score_a` missing (prod has `team_a_score`); fixed in #46 |
| `GET .../stats` | ✅ 200, 0 events |

**Shipped at:** _pending #46 + DNS_  
**Links:**  
- Sleeper: `https://mikes-hard.yetai.app` (after DNS) / `https://yetai.app/vault/mikes-hard`  
- ESPN: `https://league-838295.yetai.app` / `https://yetai.app/vault/league-838295`  

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

**Identity correction time (deliverable):**  
- Sleeper: _min_  
- ESPN: _min_  

---

## Go / no-go (fill after 2–3 weeks)

**Decision:** go / no-go / reshape  

**Reasoning:**  

**Next action:**  
