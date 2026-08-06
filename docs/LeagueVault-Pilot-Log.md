# League Vault Pilot — Observation Log

Append entries during P4 (ship & watch). Do **not** ask managers if they like it — watch what they do.

## Ship checklist

- [ ] `alembic upgrade head` (includes `lv_vault_events`)
- [ ] `sync_pilot.py` for both leagues
- [ ] `compute_pilot.py` (records + all-play)
- [ ] `prod_verify_pilot.py --api-url https://api.yetai.app` exit 0
- [ ] Wildcard `*.yetai.app` on Vercel; `api.yetai.app` still Railway
- [ ] Paste `https://mikes-hard.yetai.app` into iMessage — OG card looks right
- [ ] Same for `https://league-838295.yetai.app` (or final ESPN slug)
- [ ] Post to each group chat with **no** “product test” framing
- [ ] Note ship timestamp below

**Shipped at:** _YYYY-MM-DD HH:MM ET_  
**Links:**  
- Sleeper:  
- ESPN:  

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
| | | | | |

**Identity correction time (deliverable):**  
- Sleeper: _min_  
- ESPN: _min_  

---

## Go / no-go (fill after 2–3 weeks)

**Decision:** go / no-go / reshape  

**Reasoning:**  

**Next action:**  
